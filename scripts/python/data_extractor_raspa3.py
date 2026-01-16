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

_MC_DIR_NAME_RE = re.compile(r'^mc(\d+)(?:__(done|failed|running))?$')
_MC_NUMBER_RE = re.compile(r'mc(\d+)')
_UNSET = object()


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
        self._pressure = _UNSET
        self._temperature = _UNSET
        self._framework_density = _UNSET
        self._he_void_fraction = _UNSET
        self._henry_by_component = None
        self._rosenbluth_by_component = None

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
            comp_pattern = re.escape(component)
            # 组件块可能使用 () 或 []，优先在 Loadings 中匹配，失败回退到全文
            block_pattern = (
                r"Component\s+\d+\s+[\(\[]" + comp_pattern +
                r"[\)\]][\s\S]+?(?=Component\s+\d+\s+[\(\[]|$)"
            )
            loadings = self._get_loadings_section()
            match = re.search(block_pattern, loadings)
            if not match and loadings is not self.output_string:
                match = re.search(block_pattern, self.output_string)
            self._component_blocks[component] = match.group(0) if match else ""

        return self._component_blocks[component]

    def _get_component_block_full(self, component):
        """强制从全文获取组件块（包含 Widom/Henry/Rosenbluth 等）"""
        comp_pattern = re.escape(component)
        block_pattern = (
            r"Component\s+\d+\s+[\(\[]" + comp_pattern +
            r"[\)\]][\s\S]+?(?=Component\s+\d+\s+[\(\[]|$)"
        )
        match = re.search(block_pattern, self.output_string)
        return match.group(0) if match else ""

    def _map_values_by_component_header(self, value_pattern):
        """
        基于就近的 Component 头部匹配值（用于 Widom/Henry/Rosenbluth）

        Args:
            value_pattern: 编译后的正则，group(1) 为数值
        Returns:
            dict: {component_name: value}
        """
        headers = [(m.start(), m.group(1)) for m in self._re_components.finditer(self.output_string)]
        if not headers:
            return {}

        results = {}
        header_idx = 0
        current_comp = headers[0][1]

        for match in value_pattern.finditer(self.output_string):
            pos = match.start()
            while header_idx + 1 < len(headers) and headers[header_idx + 1][0] <= pos:
                header_idx += 1
                current_comp = headers[header_idx][1]

            value = match.group(1)
            if value == "-nan":
                results[current_comp] = None
                continue
            try:
                results[current_comp] = float(value)
            except ValueError:
                results[current_comp] = None

        return results

    def is_finished(self):
        """检查模拟是否完成"""
        return bool(self._re_finished.search(self.output_string))

    def get_pressure(self):
        """获取压力 [Pa]"""
        if self._pressure is not _UNSET:
            return self._pressure
        try:
            # 优先使用外部压力
            match = self._re_pressure_external.search(self.output_string)
            if match:
                self._pressure = float(match.group(1))
                return self._pressure

            # 备选: 平均压力
            match = self._re_pressure_average.search(self.output_string)
            if match and match.group(1) != "-nan":
                self._pressure = float(match.group(1))
                return self._pressure

            self._pressure = None
            return self._pressure
        except (ValueError, AttributeError):
            self._pressure = None
            return self._pressure

    def get_temperature(self):
        """获取温度 [K]"""
        if self._temperature is not _UNSET:
            return self._temperature
        try:
            match = self._re_temperature.search(self.output_string)
            if match:
                self._temperature = float(match.group(1))
                return self._temperature
            self._temperature = None
            return self._temperature
        except (ValueError, AttributeError):
            self._temperature = None
            return self._temperature

    def get_Framework_density(self):
        """获取框架密度 [kg/m^3]"""
        if self._framework_density is not _UNSET:
            return self._framework_density
        try:
            match = self._re_framework_density.search(self.output_string)
            if match:
                self._framework_density = float(match.group(1))
                return self._framework_density
            self._framework_density = None
            return self._framework_density
        except (ValueError, AttributeError):
            self._framework_density = None
            return self._framework_density

    def get_He_void_fraction(self):
        """获取氦空隙率"""
        if self._he_void_fraction is not _UNSET:
            return self._he_void_fraction
        try:
            match = self._re_he_void.search(self.output_string)
            if match:
                self._he_void_fraction = float(match.group(1))
                return self._he_void_fraction
            self._he_void_fraction = None
            return self._he_void_fraction
        except (ValueError, AttributeError):
            self._he_void_fraction = None
            return self._he_void_fraction

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
        temperature = self.get_temperature()

        for component in components:
            block = self._get_component_block(component)
            match = self._re_adsorption_heat.search(block)
            if match and match.group(1) != "-nan":
                try:
                    result[component] = float(match.group(1))
                except ValueError:
                    result[component] = None
            else:
                # 无限稀释: 从 Framework-molecule energy/kB 的 Average [K] 计算吸附热
                comp_pattern = re.escape(component)
                energy_pattern = (
                    r'Framework-molecule\s+energy/kB\s+\d+-\d+\s+[\(\[]' + comp_pattern +
                    r'[\)\]]:[\s\S]+?Average\s+([\d.eE+-]+|\-nan)\s+\+/-\s+[\d.eE+-]+\s+\[K\]'
                )
                energy_match = re.search(energy_pattern, self.output_string)
                if energy_match and energy_match.group(1) != "-nan" and temperature is not None:
                    try:
                        energy_value = float(energy_match.group(1))
                        result[component] = (energy_value - temperature) * 8.314462618 / 1000
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

        if self._henry_by_component is None:
            self._henry_by_component = self._map_values_by_component_header(self._re_henry)
        mapped = self._henry_by_component
        for component in components:
            value = mapped.get(component)
            result[component] = value if value is not None else None

        return result

    def get_rosenbluth_weight(self):
        """
        获取 Rosenbluth 权重

        Returns:
            dict: {组分名: Rosenbluth权重值}
        """
        result = {}
        components = self.get_components()

        if self._rosenbluth_by_component is None:
            self._rosenbluth_by_component = self._map_values_by_component_header(self._re_rosenbluth)
        mapped = self._rosenbluth_by_component
        for component in components:
            value = mapped.get(component)
            result[component] = value if value is not None else None

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
    match = _MC_NUMBER_RE.search(dir_name)
    if match:
        return int(match.group(1))
    return 0


def find_mc_dir_from_path(file_path):
    """从文件路径向上查找 mc 目录，返回 mc 目录路径和目录名"""
    current = os.path.dirname(file_path)
    while True:
        dir_name = os.path.basename(current)
        if _MC_DIR_NAME_RE.match(dir_name):
            return current, dir_name
        parent = os.path.dirname(current)
        if parent == current:
            return None, None
        current = parent


def find_all_mc_directories(base_path):
    """
    查找所有 mc 目录

    Args:
        base_path: 基础目录路径

    Returns:
        mc 目录路径列表
    """
    mc_directories = []

    base_name = os.path.basename(base_path)
    if _MC_DIR_NAME_RE.match(base_name):
        mc_directories.append(base_path)

    for root, dirs, files in os.walk(base_path):
        for dir_name in dirs:
            # 匹配 mc 数字格式的目录（包括各种状态后缀）
            if _MC_DIR_NAME_RE.match(dir_name):
                full_path = os.path.join(root, dir_name)
                mc_directories.append(full_path)

    return mc_directories


def _normalize_fw(s):
    """Normalize framework names coming from CSV (may include NaN/float)."""
    if s is None:
        return ''
    try:
        if pd.isna(s):
            return ''
    except Exception:
        pass
    if not isinstance(s, str):
        s = str(s)
    return s.strip()


def _best_item_for_framework(items):
    """从候选条目中挑选最合适的一个：优先有 out_file 的 Done > Running > Failed > Unknown，有文件优先。"""
    if not items:
        return None

    def score(it):
        s = 0
        if it.get('out_file'):
            s += 10
        st = it.get('status')
        if st == 'Done':
            s += 5
        elif st == 'Running':
            s += 3
        elif st == 'Failed':
            s += 1
        return s

    return sorted(items, key=score, reverse=True)[0]


def _scan_mc_framework_map(base_path):
    """
    扫描 mc 目录并构建 framework -> items 映射
    item: {mc_dir, status, out_file, framework}
    """
    fmap = {}
    mc_dirs = find_all_mc_directories(base_path)
    for mc_dir in mc_dirs:
        dir_name = os.path.basename(mc_dir)
        if '__done' in dir_name:
            status = 'Done'
        elif '__failed' in dir_name:
            status = 'Failed'
        elif '__running' in dir_name:
            status = 'Running'
        else:
            status = 'Unknown'

        out_file = find_output_file_in_mc_dir(mc_dir)
        framework = extract_framework_name_from_simulation_json(mc_dir) or ''

        item = {
            'mc_dir': mc_dir,
            'status': status,
            'out_file': out_file,
            'framework': framework,
        }
        fmap.setdefault(framework, []).append(item)

    return fmap


def find_all_output_files(base_path):
    """
    遍历 base_path 下所有 output 目录中的 .txt 文件

    Returns:
        输出文件路径列表
    """
    output_files = []

    for root, dirs, files in os.walk(base_path):
        if os.path.basename(root).lower() == 'output':
            for file_name in files:
                if file_name.endswith('.txt'):
                    output_files.append(os.path.join(root, file_name))

    return output_files


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


def find_and_process_files_by_csv_template(base_path, selected_items, selected_units=None, csv_file=None, framework_col=None):
    """
    以 CSV 模板顺序进行提取：
    - 顺序与 csv_file_path 中 framework_column 完全一致
    - 针对每个框架匹配 mc 目录（按框架名匹配）
    - 没有/报错的就留空并打标记（not_found / no_output / failed / running）
    """
    if not csv_file or not framework_col or not os.path.exists(csv_file):
        print("按模板对齐模式：未能读取 csv_file_path/framework_column 或 CSV 不存在，回退到目录扫描模式。")
        return find_and_process_files_high_throughput(base_path, selected_items, selected_units)

    df = pd.read_csv(csv_file, encoding='utf-8-sig')
    if framework_col not in df.columns:
        print(f"基线CSV缺少列: {framework_col}，回退到目录扫描模式。")
        return find_and_process_files_high_throughput(base_path, selected_items, selected_units)

    fw_list = [_normalize_fw(x) for x in df[framework_col].tolist()]

    fmap = _scan_mc_framework_map(base_path)

    def simple_key(s):
        s = _normalize_fw(s)
        return s.replace('.cif', '')

    loose_index = {}
    fmap_items = []
    for k, items in fmap.items():
        skey = simple_key(k)
        loose_index.setdefault(skey, []).extend(items)
        fmap_items.append((k, skey, items))

    results = []

    # 进度条开关（默认True）
    show_progress = True
    pbar = None
    if show_progress:
        try:
            from tqdm import tqdm as _tqdm
            pbar = _tqdm(total=len(fw_list), desc="Processing", unit="row")
        except Exception:
            pbar = None

    for i, fw in enumerate(fw_list, start=1):
        chosen = None
        if fw in fmap:
            chosen = _best_item_for_framework(fmap[fw])
        if not chosen:
            skey = simple_key(fw)
            if skey in loose_index:
                chosen = _best_item_for_framework(loose_index[skey])
            if not chosen:
                for k, kk, items in fmap_items:
                    if not k:
                        continue
                    if kk == skey or kk.startswith(skey) or skey.startswith(kk):
                        chosen = _best_item_for_framework(items)
                        if chosen:
                            break

        if chosen and chosen.get('out_file'):
            parsed = process_output_file(chosen['out_file'], i, selected_items, selected_units)
            if parsed:
                parsed['Framework Name'] = fw
                parsed['MC_Directory'] = os.path.basename(chosen['mc_dir'])
                parsed['Status'] = chosen['status']
                results.append(parsed)
                if pbar:
                    pbar.update(1)
                continue

        row = {
            'MC_Number': i,
            'File Path': chosen['mc_dir'] if chosen else '',
            'Framework Name': fw,
            'warnings': [],
            'MC_Directory': os.path.basename(chosen['mc_dir']) if chosen else '',
        }
        st = chosen['status'] if chosen else 'Unknown'
        row['Status'] = st
        if not chosen:
            row['warnings'] = ['not_found']
        else:
            if st == 'Done':
                row['warnings'] = ['no_output']
            elif st == 'Failed':
                row['warnings'] = ['failed']
            elif st == 'Running':
                row['warnings'] = ['running']
            else:
                row['warnings'] = ['not_started']

        results.append(row)
        if pbar:
            pbar.update(1)

    if pbar:
        pbar.close()
    return results


def find_and_process_files_high_throughput(base_path, selected_items, selected_units=None):
    """
    自动遍历 output 目录数据提取

    Args:
        base_path: 基础目录路径
        selected_items: 选择的数据项列表
        selected_units: 吸附量单位选择字典

    Returns:
        提取结果列表
    """
    all_results = []

    print("开始 RASPA3 数据提取 (遍历 output 目录)...")

    output_files = find_all_output_files(base_path)
    mc_directories = find_all_mc_directories(base_path)

    if not output_files:
        print("未找到 output 目录下的输出文件")
        # 仍然记录可能的 mc 目录缺失输出
        if not mc_directories:
            return []

    output_files.sort()

    print(f"找到 {len(output_files)} 个 output 输出文件")
    print("开始处理文件...")

    mc_with_output = set()

    with tqdm(total=len(output_files), desc="Processing", unit="file") as pbar:
        for idx, output_file in enumerate(output_files, start=1):
            mc_dir, dir_name = find_mc_dir_from_path(output_file)
            mc_number = extract_mc_number(mc_dir) if mc_dir else idx

            result = process_output_file(
                output_file, mc_number, selected_items, selected_units
            )
            if result:
                if dir_name:
                    mc_with_output.add(mc_dir)
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
                else:
                    result['Status'] = 'Unknown'
                    result['MC_Directory'] = ''

                all_results.append(result)
            pbar.update(1)

    # 为存在但无输出的 mc 目录补占位记录
    if mc_directories:
        for mc_dir in mc_directories:
            if mc_dir in mc_with_output:
                continue
            dir_name = os.path.basename(mc_dir)
            mc_number = extract_mc_number(mc_dir)
            framework_name = extract_framework_name_from_simulation_json(mc_dir) or ''

            result = {
                'MC_Number': mc_number,
                'File Path': mc_dir,
                'Framework Name': framework_name,
                'warnings': ['no_output'],
                'MC_Directory': dir_name,
            }

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

            all_results.append(result)

    # 按 mc 编号排序
    all_results.sort(key=lambda x: x['MC_Number'])

    # 输出统计信息
    done_count = len([r for r in all_results if r.get('Status') == 'Done'])
    failed_count = len([r for r in all_results if r.get('Status') == 'Failed'])
    running_count = len([r for r in all_results if r.get('Status') == 'Running'])
    unknown_count = len([r for r in all_results if r.get('Status') == 'Unknown'])

    print(f"\n处理总结:")
    print(f"总计记录数: {len(all_results)}")
    print(f"Done 状态: {done_count}")
    print(f"Failed 状态: {failed_count}")
    print(f"Running 状态: {running_count}")
    print(f"Unknown 状态: {unknown_count}")

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
