#!/usr/bin/env python3
"""
RASPA3 高通量计算数据提取器

功能:
- 从 RASPA3 输出文件 (output/*.txt) 提取数据
- 支持高通量计算模式 (mc1, mc2, mc3...)
- 提取吸附量、吸附热、亨利系数等数据
- 输出为 Excel 或 CSV 格式

用法:
    python data_extractor_raspa3.py
    或作为模块被 data_extractor.py 调用
"""

import os
import re
import sys
import json
import traceback
import logging
from datetime import datetime

try:
    from tqdm import tqdm
    import pandas as pd
except ImportError:
    print("\n需要安装 tqdm 和 pandas 库")
    print("请运行: pip install tqdm pandas")
    sys.exit(1)


def setup_logging(log_file="raspa3_data_extraction.log"):
    """设置日志系统"""
    root_logger = logging.getLogger('raspa3_extractor')
    if root_logger.handlers:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

    root_logger.setLevel(logging.DEBUG)

    file_fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_fmt = logging.Formatter('%(levelname)s - %(message)s')

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    return root_logger


logger = setup_logging()


class RASPA3_Output_Data:
    """
    RASPA3 输出文件解析类

    与 RASPA2 的主要区别:
    - 输出格式: Abs. loading average / Excess loading average (科学计数法)
    - 单位格式: [mol/kg-framework] 而非 [mol/kg framework]
    - 组件格式: Component X (Name) 或 Component X [Name]
    """

    # 预编译正则表达式
    _re_components = re.compile(r'Component\s+\d+\s+[\(\[](.+?)[\)\]]')
    _re_finished = re.compile(r'Simulation\s+finished', re.IGNORECASE)
    # 温度和压力正则 - 支持多种格式
    # 注意：排除 "Unit of temperature", "Critical temperature" 等
    _re_pressure_external = re.compile(r'^(?:External\s+)?Pressure:\s+([\d.eE+-]+)\s+\[Pa\]', re.MULTILINE)
    _re_pressure_average = re.compile(r'Pressure\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[Pa\]')
    _re_temperature = re.compile(r'^(?:External\s+)?Temperature:\s+([\d.eE+-]+)\s+\[K\]', re.MULTILINE)
    _re_framework_density = re.compile(r'Framework\s+density:\s+([\d.eE+-]+)\s+\[kg/m\^3\]')
    _re_he_void = re.compile(r'Helium\s+void[-\s]?fraction:\s+([\d.eE+-]+)')

    # RASPA3 吸附量正则 - 按单位分类
    _re_absorption_patterns = {
        'absolute': {
            'molecules/cell': re.compile(r'Abs\.\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[molecules/cell\]'),
            'mol/kg': re.compile(r'Abs\.\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[mol/kg-framework\]'),
            'mg/g': re.compile(r'Abs\.\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[mg/g-framework\]'),
            'cm^3/g': re.compile(r'Abs\.\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[cm\^3\(STP\)/g-framework\]'),
            'cm^3/cm^3': re.compile(r'Abs\.\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[cm\^3\(STP\)/cm\^3-framework\]'),
        },
        'excess': {
            'molecules/cell': re.compile(r'Excess\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[molecules/cell\]'),
            'mol/kg': re.compile(r'Excess\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[mol/kg-framework\]'),
            'mg/g': re.compile(r'Excess\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[mg/g-framework\]'),
            'cm^3/g': re.compile(r'Excess\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[cm\^3\(STP\)/g-framework\]'),
            'cm^3/cm^3': re.compile(r'Excess\s+loading\s+average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[cm\^3\(STP\)/cm\^3-framework\]'),
        }
    }

    # 吸附热
    _re_adsorption_heat = re.compile(
        r'Enthalpy\s+of\s+adsorption:\s+(?:[\d.eE+-]+|\-nan).*?\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[kJ/mol\]'
    )

    # 亨利系数
    _re_henry = re.compile(
        r'Average\s+Henry\s+coefficient:\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[mol/kg/Pa\]'
    )

    # Rosenbluth 权重
    _re_rosenbluth = re.compile(
        r'Average\s+Rosenbluth\s+weight:\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[-\]'
    )

    def __init__(self, output_string):
        """初始化时传入 RASPA3 输出文件的字符串"""
        self.output_string = output_string
        self._components = None
        self._component_blocks = None
        self._loadings_section = None

    def _get_loadings_section(self):
        """获取 Loadings 部分的内容 (吸附量数据所在位置)"""
        if self._loadings_section is None:
            # 查找 "Loadings" 标题后的内容
            match = re.search(r'Loadings\s*\n={10,}([\s\S]+?)(?=\n\w+\s*\n={10,}|Simulation\s+finished|$)', self.output_string)
            if match:
                self._loadings_section = match.group(1)
            else:
                # 备选: 查找包含 "Abs. loading average" 的区域
                self._loadings_section = self.output_string
        return self._loadings_section

    def get_components(self):
        """获取组分名称列表 (从 Loadings 部分提取)"""
        if self._components is None:
            loadings = self._get_loadings_section()
            # 在 Loadings 部分查找组件 (格式: Component X (name))
            comp_pattern = re.compile(r'Component\s+\d+\s+\(([^)]+)\)')
            self._components = list(dict.fromkeys(comp_pattern.findall(loadings)))

            # 如果 Loadings 部分没找到，回退到全文搜索
            if not self._components:
                self._components = list(dict.fromkeys(self._re_components.findall(self.output_string)))
        return self._components

    def _get_component_block(self, component):
        """获取特定组分在 Loadings 部分的数据块"""
        if self._component_blocks is None:
            self._component_blocks = {}

        if component not in self._component_blocks:
            loadings = self._get_loadings_section()
            comp_pattern = re.escape(component)
            # 匹配 Loadings 部分中的组件块 (格式: Component X (name))
            block_pattern = (
                r"Component\s+\d+\s+\(" + comp_pattern +
                r"\)[\s\S]+?(?=Component\s+\d+\s+\(|$)"
            )
            match = re.search(block_pattern, loadings)
            self._component_blocks[component] = match.group(0) if match else ""

        return self._component_blocks[component]

    def is_finished(self):
        """检查模拟是否完成"""
        return bool(self._re_finished.search(self.output_string))

    def get_pressure(self):
        """获取压力 [Pa]"""
        try:
            # 优先使用外部压力
            match = self._re_pressure_external.search(self.output_string)
            if match:
                return float(match.group(1))

            # 备选: 平均压力
            match = self._re_pressure_average.search(self.output_string)
            if match and match.group(1) != "-nan":
                return float(match.group(1))

            return None
        except (ValueError, AttributeError):
            return None

    def get_temperature(self):
        """获取温度 [K]"""
        try:
            match = self._re_temperature.search(self.output_string)
            if match:
                return float(match.group(1))
            return None
        except (ValueError, AttributeError):
            return None

    def get_Framework_density(self):
        """获取框架密度 [kg/m^3]"""
        try:
            match = self._re_framework_density.search(self.output_string)
            if match:
                return float(match.group(1))
            return None
        except (ValueError, AttributeError):
            return None

    def get_He_void_fraction(self):
        """获取氦空隙率"""
        try:
            match = self._re_he_void.search(self.output_string)
            if match:
                return float(match.group(1))
            return None
        except (ValueError, AttributeError):
            return None

    def get_absolute_adsorption(self, unit='mol/kg'):
        """
        获取绝对吸附量

        Args:
            unit: 单位，可选 'molecules/cell', 'mol/kg', 'mg/g', 'cm^3/g', 'cm^3/cm^3'

        Returns:
            dict: {组分名: 吸附量值}
        """
        result = {}
        components = self.get_components()
        pattern = self._re_absorption_patterns['absolute'].get(unit)

        if not pattern:
            logger.warning(f"不支持的吸附量单位: {unit}")
            return result

        for component in components:
            block = self._get_component_block(component)
            match = pattern.search(block)
            if match and match.group(1) != "-nan":
                try:
                    result[component] = float(match.group(1))
                except ValueError:
                    result[component] = None
            else:
                result[component] = None

        return result

    def get_excess_adsorption(self, unit='mol/kg'):
        """
        获取超额吸附量

        Args:
            unit: 单位，可选 'molecules/cell', 'mol/kg', 'mg/g', 'cm^3/g', 'cm^3/cm^3'

        Returns:
            dict: {组分名: 吸附量值}
        """
        result = {}
        components = self.get_components()
        pattern = self._re_absorption_patterns['excess'].get(unit)

        if not pattern:
            logger.warning(f"不支持的吸附量单位: {unit}")
            return result

        for component in components:
            block = self._get_component_block(component)
            match = pattern.search(block)
            if match and match.group(1) != "-nan":
                try:
                    result[component] = float(match.group(1))
                except ValueError:
                    result[component] = None
            else:
                result[component] = None

        return result

    def get_adsorption_heat(self):
        """
        获取吸附热 [kJ/mol]

        Returns:
            dict: {组分名: 吸附热值}
        """
        result = {}
        components = self.get_components()

        for component in components:
            block = self._get_component_block(component)
            match = self._re_adsorption_heat.search(block)
            if match and match.group(1) != "-nan":
                try:
                    result[component] = float(match.group(1))
                except ValueError:
                    result[component] = None
            else:
                result[component] = None

        return result

    def get_henry_coefficient(self):
        """
        获取亨利系数 [mol/kg/Pa]

        Returns:
            dict: {组分名: 亨利系数值}
        """
        result = {}
        components = self.get_components()

        for component in components:
            block = self._get_component_block(component)
            match = self._re_henry.search(block)
            if match and match.group(1) != "-nan":
                try:
                    result[component] = float(match.group(1))
                except ValueError:
                    result[component] = None
            else:
                result[component] = None

        return result

    def get_rosenbluth_weight(self):
        """
        获取 Rosenbluth 权重

        Returns:
            dict: {组分名: Rosenbluth权重值}
        """
        result = {}
        components = self.get_components()

        for component in components:
            block = self._get_component_block(component)
            match = self._re_rosenbluth.search(block)
            if match and match.group(1) != "-nan":
                try:
                    result[component] = float(match.group(1))
                except ValueError:
                    result[component] = None
            else:
                result[component] = None

        return result


def extract_framework_name_from_simulation_json(mc_dir):
    """
    从 simulation.json 中提取框架名称

    Args:
        mc_dir: mc 任务目录路径

    Returns:
        框架名称字符串，失败返回 None
    """
    try:
        sim_json_path = os.path.join(mc_dir, 'simulation.json')
        if os.path.exists(sim_json_path):
            with open(sim_json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 从 Systems[0].Name 提取框架名
            if 'Systems' in config and len(config['Systems']) > 0:
                name_path = config['Systems'][0].get('Name', '')
                # 提取路径中的最后一部分作为框架名
                framework_name = os.path.basename(name_path)
                # 移除可能的 .cif 后缀
                if framework_name.lower().endswith('.cif'):
                    framework_name = framework_name[:-4]
                return framework_name
        return None
    except Exception as e:
        logger.debug(f"从 simulation.json 提取框架名失败: {e}")
        return None


def find_output_file_in_mc_dir(mc_dir):
    """
    在 mc 目录中查找 RASPA3 输出文件

    RASPA3 输出位置: output/*.txt 或 output/*.s0.txt

    Args:
        mc_dir: mc 任务目录路径

    Returns:
        输出文件路径，未找到返回 None
    """
    # RASPA3 输出目录通常是小写 'output'
    output_dirs = [
        os.path.join(mc_dir, 'output'),
        os.path.join(mc_dir, 'Output'),
        os.path.join(mc_dir, 'OUTPUT'),
    ]

    for output_dir in output_dirs:
        if os.path.isdir(output_dir):
            # 查找 .txt 文件
            try:
                for entry in os.scandir(output_dir):
                    if entry.is_file() and entry.name.endswith('.txt'):
                        return entry.path
            except PermissionError:
                continue

    return None


def extract_mc_number(mc_dir_path):
    """从 mc 目录路径中提取编号"""
    dir_name = os.path.basename(mc_dir_path)
    match = re.search(r'mc(\d+)', dir_name)
    if match:
        return int(match.group(1))
    return 0


def find_all_mc_directories(base_path):
    """
    查找所有 mc 目录

    Args:
        base_path: 基础目录路径

    Returns:
        mc 目录路径列表
    """
    mc_directories = []

    for root, dirs, files in os.walk(base_path):
        for dir_name in dirs:
            # 匹配 mc 数字格式的目录（包括各种状态后缀）
            if re.match(r'mc\d+(__done|__failed|__running)?$', dir_name):
                full_path = os.path.join(root, dir_name)
                mc_directories.append(full_path)

    return mc_directories


def process_output_file(file_path, mc_number, selected_items, selected_units=None):
    """
    处理单个 RASPA3 输出文件

    Args:
        file_path: 输出文件路径
        mc_number: mc 任务编号
        selected_items: 选择的数据项列表
        selected_units: 吸附量单位选择字典

    Returns:
        提取的数据字典，失败返回 None
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        raspa_data = RASPA3_Output_Data(content)

        # 从 mc 目录提取框架名
        mc_dir = os.path.dirname(os.path.dirname(file_path))  # output 上级
        framework_name = extract_framework_name_from_simulation_json(mc_dir)

        result = {
            'MC_Number': mc_number,
            'File Path': file_path,
            'Framework Name': framework_name or '',
            'warnings': []
        }

        # 检查模拟状态
        if not raspa_data.is_finished():
            result['warnings'].append('not_finished')

        # 根据选择的项目提取数据
        if 'pressure' in selected_items:
            result['pressure'] = raspa_data.get_pressure()

        if 'temperature' in selected_items:
            result['temperature'] = raspa_data.get_temperature()

        if 'He_void_fraction' in selected_items:
            result['He_void_fraction'] = raspa_data.get_He_void_fraction()

        if 'Framework_density' in selected_items:
            result['Framework_density'] = raspa_data.get_Framework_density()

        if 'absolute_adsorption' in selected_items:
            unit = (selected_units or {}).get('absolute_adsorption', 'mol/kg')
            data = raspa_data.get_absolute_adsorption(unit)
            for comp, value in data.items():
                key = f'{comp}_absolute_{unit.replace("/", "_per_").replace("^", "")}'
                result[key] = value

        if 'excess_adsorption' in selected_items:
            unit = (selected_units or {}).get('excess_adsorption', 'mol/kg')
            data = raspa_data.get_excess_adsorption(unit)
            for comp, value in data.items():
                key = f'{comp}_excess_{unit.replace("/", "_per_").replace("^", "")}'
                result[key] = value

        if 'adsorption_heat' in selected_items:
            data = raspa_data.get_adsorption_heat()
            for comp, value in data.items():
                result[f'{comp}_adsorption_heat'] = value

        if 'henry_coefficient' in selected_items:
            data = raspa_data.get_henry_coefficient()
            for comp, value in data.items():
                result[f'{comp}_henry_coefficient'] = value

        if 'rosenbluth_weight' in selected_items:
            data = raspa_data.get_rosenbluth_weight()
            for comp, value in data.items():
                result[f'{comp}_rosenbluth_weight'] = value

        return result

    except Exception as e:
        logger.error(f"处理文件时出错 {file_path}: {e}")
        return None


def find_and_process_files_high_throughput(base_path, selected_items, selected_units=None):
    """
    高通量模式数据提取

    按 mc1, mc2, mc3... 顺序处理 RASPA3 输出

    Args:
        base_path: 基础目录路径
        selected_items: 选择的数据项列表
        selected_units: 吸附量单位选择字典

    Returns:
        提取结果列表
    """
    all_results = []

    print("开始 RASPA3 高通量计算数据提取...")

    # 查找所有 mc 目录
    mc_directories = find_all_mc_directories(base_path)

    if not mc_directories:
        print("未找到 mc 目录结构")
        return []

    print(f"找到 {len(mc_directories)} 个 mc 目录")

    # 按 mc 编号排序
    mc_directories.sort(key=lambda x: extract_mc_number(x))

    print("开始处理目录...")

    with tqdm(total=len(mc_directories), desc="Processing", unit="dir") as pbar:
        for mc_dir in mc_directories:
            mc_number = extract_mc_number(mc_dir)
            dir_name = os.path.basename(mc_dir)
            output_file = find_output_file_in_mc_dir(mc_dir)

            if output_file:
                result = process_output_file(
                    output_file, mc_number, selected_items, selected_units
                )
                if result:
                    # 添加状态信息
                    if '__done' in dir_name:
                        result['Status'] = 'Done'
                    elif '__failed' in dir_name:
                        result['Status'] = 'Failed'
                        result['warnings'].append('failed')
                    elif '__running' in dir_name:
                        result['Status'] = 'Running'
                        result['warnings'].append('running')
                    else:
                        result['Status'] = 'Unknown'

                    result['MC_Directory'] = dir_name
                    all_results.append(result)
                    pbar.update(1)
                    continue

            # 没有输出文件，创建占位记录
            framework_name = extract_framework_name_from_simulation_json(mc_dir) or ''

            result = {
                'MC_Number': mc_number,
                'File Path': mc_dir,
                'Framework Name': framework_name,
                'warnings': [],
                'MC_Directory': dir_name,
            }

            if '__done' in dir_name:
                result['Status'] = 'Done'
                result['warnings'] = ['no_output']
            elif '__failed' in dir_name:
                result['Status'] = 'Failed'
                result['warnings'] = ['failed']
            elif '__running' in dir_name:
                result['Status'] = 'Running'
                result['warnings'] = ['running']
            else:
                result['Status'] = 'Unknown'
                result['warnings'] = ['not_started']

            all_results.append(result)
            pbar.update(1)

    # 按 mc 编号排序
    all_results.sort(key=lambda x: x['MC_Number'])

    # 输出统计信息
    done_count = len([r for r in all_results if r.get('Status') == 'Done'])
    failed_count = len([r for r in all_results if r.get('Status') == 'Failed'])
    running_count = len([r for r in all_results if r.get('Status') == 'Running'])

    print(f"\n处理总结:")
    print(f"总计 mc 目录数: {len(all_results)}")
    print(f"Done 状态: {done_count}")
    print(f"Failed 状态: {failed_count}")
    print(f"Running 状态: {running_count}")

    return all_results


def save_results_to_file(results, output_file='raspa3_results.xlsx', format_type='excel'):
    """
    保存提取的数据到文件

    Args:
        results: 提取结果列表
        output_file: 输出文件路径
        format_type: 输出格式 ('excel' 或 'csv')

    Returns:
        是否保存成功
    """
    try:
        data_rows = []

        for result in results:
            row = {
                'File Path': result.get('File Path', ''),
                'Framework Name': result.get('Framework Name', ''),
                'Warnings': '; '.join(result.get('warnings', [])) if result.get('warnings') else '',
            }

            for key, value in result.items():
                if key in ['MC_Number', 'MC_Directory', 'Status', 'Framework Name', 'File Path', 'warnings']:
                    continue

                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        row[f"{key}_{sub_key}"] = sub_value
                else:
                    row[key] = value

            data_rows.append(row)

        df = pd.DataFrame(data_rows)

        if df.empty:
            print("没有数据可保存")
            return False

        # 重新排列列顺序
        columns = ['File Path', 'Framework Name', 'Warnings']

        # 基本参数列
        basic_columns = ['pressure', 'temperature', 'He_void_fraction', 'Framework_density']
        for col in basic_columns:
            if col in df.columns:
                columns.append(col)

        # 吸附量列
        adsorption_columns = [col for col in df.columns if '_absolute_' in col or '_excess_' in col]
        columns.extend(sorted(adsorption_columns))

        # 吸附热和亨利系数列
        other_columns = [col for col in df.columns if '_adsorption_heat' in col or '_henry_coefficient' in col or '_rosenbluth_weight' in col]
        columns.extend(sorted(other_columns))

        # 其他列
        remaining_columns = [col for col in df.columns if col not in columns]
        columns.extend(remaining_columns)

        df = df[columns]

        # 保存文件
        if format_type.lower() == 'csv':
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            print(f"\n数据已保存到 {output_file} (CSV格式)")
        else:
            df.to_excel(output_file, index=False)
            print(f"\n数据已保存到 {output_file} (Excel格式)")

        return True
    except Exception as e:
        print(f"\n保存数据时出错: {e}")
        traceback.print_exc()
        return False


def main():
    """主函数 - 独立运行时的入口"""
    print("=== RASPA3 数据提取工具 ===")
    print("该工具将从指定目录中提取 RASPA3 输出文件的数据")

    # 获取目录路径
    base_path = input("请输入要提取数据的目录路径: ").strip()
    if not base_path:
        base_path = os.getcwd()

    if not os.path.exists(base_path):
        print(f"错误: 目录 '{base_path}' 不存在")
        return

    # 选择输出格式
    print("\n选择输出格式:")
    print("1. Excel格式 (.xlsx)")
    print("2. CSV格式 (.csv)")
    format_choice = input("请选择输出格式 (1/2, 默认为Excel): ").strip()

    if format_choice == '2':
        output_format = 'csv'
        default_filename = 'raspa3_results.csv'
    else:
        output_format = 'excel'
        default_filename = 'raspa3_results.xlsx'

    # 选择要提取的数据项
    options_dict = {
        '1': 'pressure',
        '2': 'temperature',
        '3': 'He_void_fraction',
        '4': 'Framework_density',
        '5': 'absolute_adsorption',
        '6': 'excess_adsorption',
        '7': 'adsorption_heat',
        '8': 'henry_coefficient',
        '9': 'rosenbluth_weight'
    }

    # 默认选择所有项
    selected_items = list(options_dict.values())

    # 询问是否自定义选择
    custom_select = input("\n是否自定义选择要提取的数据项? (默认提取所有数据) (y/n): ").strip().lower()

    if custom_select == 'y':
        print("\n请选择要提取的数据项（输入对应的数字，用逗号分隔）：")
        print("1. Pressure (压力)")
        print("2. Temperature (温度)")
        print("3. He Void Fraction (氦空隙率)")
        print("4. Framework Density (框架密度)")
        print("5. Absolute Adsorption (绝对吸附量)")
        print("6. Excess Adsorption (超额吸附量)")
        print("7. Adsorption Heat (吸附热)")
        print("8. Henry Coefficient (亨利系数)")
        print("9. Rosenbluth Weight (Rosenbluth权重)")

        selected_numbers = input("您的选择：").strip()

        if selected_numbers:
            selected_items = []
            for num in selected_numbers.split(','):
                num = num.strip()
                if num in options_dict:
                    selected_items.append(options_dict[num])

    print("\n将提取以下数据项：")
    for item in selected_items:
        print(f"- {item}")

    # 选择单位
    selected_units = {}
    if 'absolute_adsorption' in selected_items or 'excess_adsorption' in selected_items:
        unit_options = {
            '1': 'molecules/cell',
            '2': 'mol/kg',
            '3': 'mg/g',
            '4': 'cm^3/g',
            '5': 'cm^3/cm^3',
        }

        if 'absolute_adsorption' in selected_items:
            print("\n绝对吸附量单位选择:")
            print("1. molecules/cell  2. mol/kg  3. mg/g  4. cm^3/g  5. cm^3/cm^3")
            choice = input("请选择绝对吸附量单位 (默认: 2): ").strip()
            selected_units['absolute_adsorption'] = unit_options.get(choice, 'mol/kg')

        if 'excess_adsorption' in selected_items:
            print("\n超额吸附量单位选择:")
            print("1. molecules/cell  2. mol/kg  3. mg/g  4. cm^3/g  5. cm^3/cm^3")
            choice = input("请选择超额吸附量单位 (默认: 2): ").strip()
            selected_units['excess_adsorption'] = unit_options.get(choice, 'mol/kg')

    # 设置输出文件名
    output_file = input(f"\n请输入输出文件名 (默认为 '{default_filename}'): ").strip()
    if not output_file:
        output_file = default_filename

    # 确保文件扩展名正确
    if output_format == 'csv' and not output_file.endswith('.csv'):
        output_file = output_file.rsplit('.', 1)[0] + '.csv'
    elif output_format == 'excel' and not output_file.endswith('.xlsx'):
        output_file = output_file.rsplit('.', 1)[0] + '.xlsx'

    # 开始提取数据
    print(f"\n开始从 {base_path} 提取 RASPA3 数据...")

    results = find_and_process_files_high_throughput(base_path, selected_items, selected_units)

    if results:
        save_results_to_file(results, output_file, output_format)
        print(f"\n✓ 数据提取成功。共处理 {len(results)} 个目录。")
        print(f"✓ 结果已保存到 '{output_file}'")
    else:
        print("\n✗ 未找到数据文件或所有处理失败。")


if __name__ == "__main__":
    main()
