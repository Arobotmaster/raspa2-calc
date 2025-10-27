#!/usr/bin/env python3

import os
import re
import sys
import traceback
from datetime import datetime
import yaml
from concurrent.futures import ProcessPoolExecutor, as_completed

try:
    from tqdm import tqdm  # 用于显示进度条
    import pandas as pd    # 用于处理Excel输出
except ImportError:
    print("\n需要安装tqdm和pandas库才能运行数据提取功能")
    print("请运行: pip install tqdm pandas")
    sys.exit(1)

class RASPA_Output_Data():
    '''
        RASPA输出文件对象
    '''

    # 预编译正则以减少重复编译开销
    _re_components = re.compile(r'Component \d+ \[(.*)\] \(Adsorbate molecule\)')
    _re_finished = re.compile(r'Simulation finished')
    _re_warnings_zero = re.compile(r'0 warnings')
    _re_warning = re.compile(r'WARNING: (.*)\n')
    _re_pressure = re.compile(r'Pressure:\s+(.*)\s+\[Pa\]')
    _re_he_void = re.compile(r'Helium VoidFraction:\s+(.*)\n')
    _re_sa_mass = re.compile(r'Surface area per mass:\s+(.*)\s+\[m\^2\/g\]')
    _re_sa_volume = re.compile(r'Surface area per volume:\s+(.*)\s+\[m\^2\/cm\^3\]')
    _re_henry = re.compile(
        r'\[\s*(?P<component>.*?)\s*\]\s+Average Henry coefficient:\s+'
        r'(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'
        r'(?:\s+\+/-\s+(?P<error>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))?'
        r'\s+\[mol/kg/Pa\]'
    )
    _re_framework_density = re.compile(r'Framework density:\s+(.*)\s+\[kg\/m\^3\]')
    _re_inf_dilution_energy = re.compile(
        r'Total energy:\n=============\n(?:.*\n)*?\s*-+\n\s*Average\s+(\-?\d+\.?\d*)\s+\[K\]'
    )

    # 为吸附量按单位预编译正则
    _re_absorption_patterns = {
        'absolute': {
            'mol/kg': re.compile(r'Average loading absolute \[mol\/kg framework\]\s+([\d\.]+)\s+\+/-'),
            'cm^3/g': re.compile(r'Average loading absolute \[cm\^3 \(STP\)\/gr framework\]\s+([\d\.]+)\s+\+/-'),
            'mg/g': re.compile(r'Average loading absolute \[milligram\/gram framework\]\s+([\d\.]+)\s+\+/-'),
            'cm^3/cm^3': re.compile(r'Average loading absolute \[cm\^3 \(STP\)\/cm\^3 framework\]\s+([\d\.]+)\s+\+/-'),
        },
        'excess': {
            'mol/kg': re.compile(r'Average loading excess \[mol\/kg framework\]\s+([\d\.]+)\s+\+/-'),
            'cm^3/g': re.compile(r'Average loading excess \[cm\^3 \(STP\)\/gr framework\]\s+([\d\.]+)\s+\+/-'),
            'mg/g': re.compile(r'Average loading excess \[milligram\/gram framework\]\s+([\d\.]+)\s+\+/-'),
            'cm^3/cm^3': re.compile(r'Average loading excess \[cm\^3 \(STP\)\/cm\^3 framework\]\s+([\d\.]+)\s+\+/-'),
        }
    }

    def __init__(self, output_string):
        '''
            初始化时传入RASPA输出文件的字符串
        '''
        self.output_string = output_string
        # 惰性计算components，只有在需要时才解析
        self._components = None

    def get_components(self):
        if self._components is None:
            self._components = self._re_components.findall(self.output_string)
        return self._components

    def is_finished(self):
        '''
            返回该任务是否已完成
        '''
        return bool(self._re_finished.search(self.output_string))

    def get_warnings(self):
        '''
            返回存储警告信息的列表
        '''
        if self._re_warnings_zero.search(self.output_string):
            return []
        return list(set(self._re_warning.findall(self.output_string)))

    def get_pressure(self):
        '''
            返回压力，单位是Pa
        '''
        try:
            result = self._re_pressure.findall(self.output_string)
            return result[0] if result else None
        except Exception as e:
            print(f"Error parsing pressure: {str(e)}")
            return None

    def get_He_void_fraction(self):
        '''
            返回氦原子可占体积分数（孔隙率）
        '''
        try:
            result = self._re_he_void.findall(self.output_string)
            return result[0] if result else None
        except Exception as e:
            print(f"Error parsing He void fraction: {str(e)}")
            return None

    def get_Surface_Area(self, unit='m^2/cm^3'):
        '''
            返回比表面积，根据参数unit的值返回不同单位的比表面积值
            unit 可以是：'m^2/g', 'm^2/cm^3'
        '''
        try:
            if unit == 'm^2/g':
                result = self._re_sa_mass.findall(self.output_string)
            elif unit == 'm^2/cm^3':
                result = self._re_sa_volume.findall(self.output_string)
            else:
                raise ValueError("Unsupported unit for surface area")
            return result[0] if result else None
        except Exception as e:
            print(f"Error parsing surface area: {str(e)}")
            return None

    def get_adsorption_heat(self):
        '''
            返回吸附热(KJ/mol)，该数值使用波动法计算 fluctuation formula
            返回值是一个字典，键是吸附质的名称，值是吸附热;
        '''
        try:
            result = {}
            # 定义第一种情况下的正则表达式模式
            pattern1 = r'Enthalpy of adsorption component \d+ \[(.*)\]\n\s*-*\n.*\n.*\n.*\n.*\n.*\n\s*-*\n.*\n\s+(\-?\d+\.?\d*)\s+'

            # 定义第二种情况下的正则表达式模式
            pattern2 = r'Total enthalpy of adsorption\n.*\n.*\n.*\n.*\n.*\n.*\n.*\n.*\n\s+(\-?\d+\.?\d*)\s+'

            # 尝试匹配pattern1
            data1 = re.findall(pattern1, self.output_string)

            if data1:
                for comp, value in data1:
                    result[comp] = value  # 使用匹配到的吸附质名称和对应的吸附热值
            else:
                # 如果pattern1匹配不成功，则匹配pattern2
                data2 = re.findall(pattern2, self.output_string)
                if data2:
                    result["Total enthalpy of adsorption"] = data2[0]
            return result
        except Exception as e:
            print(f"Error parsing adsorption heat: {str(e)}")
            return {}

    def get_adsorption_heat_infinite_dilution(self, temperature=None):
        '''
            返回无限稀释吸附热数据
            从Total energy部分提取数据，返回字典包含原始能量值和计算的吸附热
            temperature: 用于计算的温度值(K)，如果为None则不计算吸附热
            返回值: {'energy_value': float, 'adsorption_heat': float or None}
        '''
        try:
            # 正则表达式模式用于匹配Total energy部分的Average值
            data = self._re_inf_dilution_energy.findall(self.output_string)
            
            if data:
                # 提取第一个匹配的Average值
                energy_value = float(data[0])
                
                result = {
                    'energy_value': energy_value,
                    'adsorption_heat': None
                }
                
                # 如果提供了温度，则计算吸附热
                if temperature is not None:
                    '''∆H = ∆U − RT = [Uhg] − [Uh] − [Ug] − RT
                       利用该公式进行吸附热换算，∆H单位为K，框架为刚性Uh = 0，气体分子能量Ug=0,能量主要来自气体分子与框架的相互作用
                       转换为kJ/mol: (energy_value - temperature) * 8.314462618/1000
                    '''
                    result['adsorption_heat'] = (energy_value - temperature) * 8.314462618 / 1000
                
                return result
            else:
                return None
        except Exception as e:
            print(f"Error parsing infinite dilution adsorption heat: {str(e)}")
            return None

    def get_henry_coefficient(self):
        '''
            返回亨利系数，单位 mol/kg/Pa
            返回值是一个字典，键是吸附质的名称，值是亨利系数
        '''
        try:
            result = {}
            for match in self._re_henry.finditer(self.output_string):
                comp = match.group('component').strip()
                value = match.group('value')
                if comp:
                    result[comp] = value
            return result
        except Exception as e:
            print(f"Error parsing henry coefficient: {str(e)}")
            return {}

    def get_Framework_density(self):
        '''
            返回框架密度，单位 kg/m^3
        '''
        try:
            result = self._re_framework_density.findall(self.output_string)
            return result[0] if result else None
        except Exception as e:
            print(f"Error parsing framework density: {str(e)}")
            return None

    def get_excess_adsorption(self, unit='cm^3/g'):
        '''
            返回超额吸附量，根据参数unit的值返回不同单位的吸附量值
            unit 可以是：'mol/kg', 'cm^3/g', 'mg/g', 'cm^3/cm^3'
        '''
        try:
            result = {}
            
            # 首先获取组分名称
            components = self.get_components()
            
            pattern = self._re_absorption_patterns['excess'].get(unit)
            if pattern is None:
                raise ValueError("Unsupported unit for excess adsorption")
            
            matches = pattern.findall(self.output_string)
            
            # 将匹配的值与组分名称配对
            for i, value in enumerate(matches):
                if i < len(components):
                    comp_name = components[i]
                else:
                    comp_name = f'Component_{i}'
                result[comp_name] = value
            
            return result
        except Exception as e:
            print(f"Error parsing excess adsorption: {str(e)}")
            return {}

    def get_absolute_adsorption(self, unit='cm^3/g'):
        '''
            返回绝对吸附量，根据参数unit的值返回不同单位的吸附量值
            unit 可以是：'mol/kg', 'cm^3/g', 'mg/g', 'cm^3/cm^3'
        '''
        try:
            result = {}
            
            # 首先获取组分名称
            components = self.get_components()
            
            pattern = self._re_absorption_patterns['absolute'].get(unit)
            if pattern is None:
                raise ValueError("Unsupported unit for absolute adsorption")
            
            matches = pattern.findall(self.output_string)
            
            # 将匹配的值与组分名称配对
            for i, value in enumerate(matches):
                if i < len(components):
                    comp_name = components[i]
                else:
                    comp_name = f'Component_{i}'
                result[comp_name] = value
            
            return result
        except Exception as e:
            print(f"Error parsing absolute adsorption: {str(e)}")
            return {}

def extract_framework_name_from_filepath(file_path):
    """
    从文件路径中提取框架名称
    例如：从 output_41467_2015_BFncomms7350_MOESM943_ESM_1_ASR_pacman_2.2.2_493.000000_10000.data 中提取 41467_2015_BFncomms7350_MOESM943_ESM_1_ASR_pacman
    """
    try:
        # 获取文件名
        filename = os.path.basename(file_path)
        
        # 新的提取逻辑：从output_到数字参数模式之间的内容
        
        # 方法1：查找从output_开始到温度参数（形如_298.000000或_493.000000）之前的内容
        pattern = r'output_(.+?)_\d+\.\d+_\d+\.\d+_\d+\.data'
        match = re.search(pattern, filename)
        
        if match:
            return match.group(1)
        
        # 方法2：处理形如 output_MOF_5_298.0_101325.data 的情况
        # 这里我们需要区分框架名称中的数字和参数数字
        # 对于 MOF_5 这样的名称，5是框架名称的一部分，不是参数
        pattern2 = r'output_(.+?)_\d+(?:\.\d+)+(?:_\d+(?:\.\d+)*)*(?:\.data)?$'
        match2 = re.search(pattern2, filename)
        
        if match2:
            framework_part = match2.group(1)
            return framework_part
        
        # 方法3：更宽松的匹配，对于不有小数点的情况
        pattern3 = r'output_(.+?)_\d+_\d+(?:\.data)?$'
        match3 = re.search(pattern3, filename)
        
        if match3:
            framework_part = match3.group(1)
            return framework_part
        
        # 方法4：如果以上都不匹配，尝试原来的简单模式
        pattern4 = r'output_([^._]+)'
        match4 = re.search(pattern4, filename)
        if match4:
            return match4.group(1)
        
        return None
    except Exception as e:
        print(f"提取框架名称时出错: {str(e)}")
        return None

def extract_framework_name_from_input_file(mc_dir):
    """
    从mc目录下的input文件中提取FrameworkName
    这是备用方法，当从文件名提取失败时使用
    """
    try:
        # 查找可能的input文件位置
        possible_input_paths = [
            os.path.join(mc_dir, 'simulation.input'),
            os.path.join(mc_dir, 'input'),
            os.path.join(mc_dir, 'INPUT'),
        ]
        
        for input_path in possible_input_paths:
            if os.path.exists(input_path):
                with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('FrameworkName'):
                            # 提取FrameworkName后面的值
                            parts = line.split()
                            if len(parts) >= 2:
                                return parts[1]
                break
        
        return None
    except Exception as e:
        print(f"从input文件提取框架名称时出错: {str(e)}")
        return None

def process_output_file(file_path, mc_number, selected_items, temperature=None, selected_units=None, parse_warnings=True):
    """
    处理单个输出文件，提取数据
    temperature: 用于计算无限稀释吸附热的温度值(K)
    """
    try:
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # 创建RASPA输出数据对象
        raspa_data = RASPA_Output_Data(content)

        # 从文件路径提取框架名称
        framework_name = extract_framework_name_from_filepath(file_path)
        
        # 如果从文件名提取失败或提取的名称不完整，尝试从mc目录的input文件中提取
        if not framework_name or len(framework_name) < 5:  # 如果提取的名称太短，可能不完整
            # 从文件路径找到mc目录
            mc_dir = None
            path_parts = file_path.split(os.sep)
            for i, part in enumerate(path_parts):
                if re.match(r'mc\d+', part):
                    mc_dir = os.sep.join(path_parts[:i+1])
                    break
            
            if mc_dir:
                input_framework_name = extract_framework_name_from_input_file(mc_dir)
                if input_framework_name:
                    framework_name = input_framework_name
                    print(f"从 input 文件提取到框架名称: {framework_name}")

        # 初始化结果字典
        result = {
            'MC_Number': mc_number,
            'File Path': file_path,
            'Framework Name': framework_name or '',
            'warnings': raspa_data.get_warnings() if parse_warnings else []
        }

        # 根据选择的项目提取数据
        if 'pressure' in selected_items:
            result['pressure'] = raspa_data.get_pressure()

        if 'He_void_fraction' in selected_items:
            result['He_void_fraction'] = raspa_data.get_He_void_fraction()

        if 'Framework_density' in selected_items:
            result['Framework_density'] = raspa_data.get_Framework_density()

        if 'Surface_Area' in selected_items:
            result['Surface_Area_m2_g'] = raspa_data.get_Surface_Area('m^2/g')
            result['Surface_Area_m2_cm3'] = raspa_data.get_Surface_Area('m^2/cm^3')

        if 'absolute_adsorption' in selected_items:
            # 仅提取用户选择的单位，默认使用 cm^3/g
            units = [selected_units.get('absolute_adsorption', 'cm^3/g')] if selected_units else ['cm^3/g']
            for unit in units:
                data = raspa_data.get_absolute_adsorption(unit)
                for comp, value in data.items():
                    result[f'{comp}_absolute_{unit.replace("/", "_per_").replace("^", "")}'] = value

        if 'excess_adsorption' in selected_items:
            # 仅提取用户选择的单位，默认使用 cm^3/g
            units = [selected_units.get('excess_adsorption', 'cm^3/g')] if selected_units else ['cm^3/g']
            for unit in units:
                data = raspa_data.get_excess_adsorption(unit)
                for comp, value in data.items():
                    result[f'{comp}_excess_{unit.replace("/", "_per_").replace("^", "")}'] = value

        if 'adsorption_heat' in selected_items:
            adsorption_heat_data = raspa_data.get_adsorption_heat()
            for comp, value in adsorption_heat_data.items():
                result[f'{comp}_adsorption_heat'] = value

        if 'adsorption_heat_infinite_dilution' in selected_items:
            infinite_dilution_data = raspa_data.get_adsorption_heat_infinite_dilution(temperature)
            if infinite_dilution_data:
                result['total_energy_value'] = infinite_dilution_data['energy_value']
                result['adsorption_heat_infinite_dilution'] = infinite_dilution_data['adsorption_heat']
            else:
                result['total_energy_value'] = None
                result['adsorption_heat_infinite_dilution'] = None

        if 'henry_coefficient' in selected_items:
            henry_data = raspa_data.get_henry_coefficient()
            for comp, value in henry_data.items():
                result[f'{comp}_henry_coefficient'] = value

        return result

    except Exception as e:
        print(f"处理文件时出错 {file_path}: {str(e)}")
        return None

def find_all_mc_directories(base_path):
    """
    查找所有mc目录，包括有输出文件和没有输出文件的
    """
    mc_directories = []
    
    print("搜索所有mc目录...")
    
    # 查找所有mc目录（包括__done和__failed状态）
    for root, dirs, files in os.walk(base_path):
        for dir_name in dirs:
            # 匹配mc数字格式的目录（包括各种状态）
            if re.match(r'mc\d+(__done|__failed|__running)?$', dir_name):
                full_path = os.path.join(root, dir_name)
                mc_directories.append(full_path)
    
    print(f"找到 {len(mc_directories)} 个mc目录")
    return mc_directories

def find_output_file_in_mc_dir(mc_dir):
    """
    在mc目录中查找输出文件
    """
    # 查找输出文件的几种可能位置
    possible_output_paths = [
        os.path.join(mc_dir, 'Output', 'System_0'),
        os.path.join(mc_dir, 'output', 'System_0'),
        os.path.join(mc_dir, 'OUTPUT', 'System_0'),
        mc_dir  # 直接在mc目录中
    ]
    
    for output_path in possible_output_paths:
        if os.path.exists(output_path):
            # 查找.data文件 (使用scandir更快，并可提前返回)
            try:
                with os.scandir(output_path) as it:
                    for entry in it:
                        if entry.is_file():
                            name = entry.name
                            if name.endswith('.data') and ('output' in name.lower()):
                                return entry.path
            except PermissionError:
                continue
    
    # 如果还没找到，尝试查找名为'output'的文件
    try:
        with os.scandir(mc_dir) as it:
            for entry in it:
                if entry.is_file() and entry.name.lower() == 'output':
                    return entry.path
    except PermissionError:
        pass
    
    return None

def extract_mc_number(mc_dir_path):
    """从mc目录路径中提取数字"""
    dir_name = os.path.basename(mc_dir_path)
    # 匹配mc后面的数字，忽略__done、__failed等后缀
    match = re.search(r'mc(\d+)', dir_name)
    if match:
        return int(match.group(1))
    return 0

def _process_single_mc_dir(mc_dir, selected_items, temperature, selected_units, parse_warnings):
    """工作进程：处理单个mc目录，返回结果字典（含占位行逻辑）。"""
    try:
        mc_number = extract_mc_number(mc_dir)
        dir_name = os.path.basename(mc_dir)
        output_file = find_output_file_in_mc_dir(mc_dir)

        if output_file:
            result = process_output_file(
                output_file,
                mc_number,
                selected_items,
                temperature,
                selected_units,
                parse_warnings=parse_warnings,
            )
            if result:
                # 添加状态信息和状态标记（与串行逻辑保持一致）
                if '__done' in dir_name:
                    result['Status'] = 'Done'
                elif '__failed' in dir_name:
                    result['Status'] = 'Failed'
                    if not result.get('warnings'):
                        result['warnings'] = ['failed']
                    else:
                        result['warnings'].append('failed')
                elif '__running' in dir_name:
                    result['Status'] = 'Running'
                    if not result.get('warnings'):
                        result['warnings'] = ['running']
                    else:
                        result['warnings'].append('running')
                else:
                    result['Status'] = 'Unknown'
                    if not result.get('warnings'):
                        result['warnings'] = ['not_started']
                    else:
                        result['warnings'].append('not_started')

                result['MC_Directory'] = dir_name
                return result
            # 若解析失败则回退为占位记录

        # 没有输出文件或解析失败，创建占位记录
        # 尝试从 simulation.input 中补全关键信息，便于后续“警告提取/重算”流程使用
        framework_name_fallback = ''
        try:
            sim_input = os.path.join(mc_dir, 'simulation.input')
            if os.path.exists(sim_input):
                with open(sim_input, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        # Example: "FrameworkName QOTLOD01_ASR"
                        if 'FrameworkName' in line:
                            parts = line.strip().split()
                            if len(parts) >= 2:
                                framework_name_fallback = parts[-1]
                            break
        except Exception:
            # 兜底：保持空值
            pass

        # File Path 使用 mc 目录做占位，避免在导出CSV时出现空字段
        result = {
            'MC_Number': mc_number,
            'File Path': mc_dir,
            'Framework Name': framework_name_fallback,
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

        # 为选择的数据项添加空值
        for item in selected_items:
            if item == 'Surface_Area':
                result['Surface_Area_m2_g'] = ''
                result['Surface_Area_m2_cm3'] = ''
            elif item == 'adsorption_heat_infinite_dilution':
                result['total_energy_value'] = ''
                result['adsorption_heat_infinite_dilution'] = ''
            elif item in ['absolute_adsorption', 'excess_adsorption']:
                pass
            else:
                result[item] = ''

        return result
    except Exception as e:
        # 极端情况下的兜底：返回最小信息，标注error
        try:
            mc_number = extract_mc_number(mc_dir)
            dir_name = os.path.basename(mc_dir)
        except Exception:
            mc_number = 0
            dir_name = os.path.basename(mc_dir) if isinstance(mc_dir, str) else ''
        return {
            'MC_Number': mc_number,
            'File Path': '',
            'Framework Name': '',
            'warnings': ['error'],
            'MC_Directory': dir_name,
            'Status': 'Unknown',
        }


def find_and_process_files_high_throughput(base_path, selected_items, output_format='excel', temperature=None, selected_units=None, parse_warnings=True, parallel=False, workers=None):
    """
    专门处理高通量计算的文件处理函数
    按mc1, mc2, mc3...的顺序处理并提取数据，包括没有输出文件的目录
    """
    all_results = []

    print("开始高通量计算数据提取...")
    
    # 查找所有mc目录
    mc_directories = find_all_mc_directories(base_path)
    
    if not mc_directories:
        print("未找到mc目录结构。")
        return []

    print("按mc目录编号排序...")
    # 按mc目录编号排序
    mc_directories.sort(key=lambda x: extract_mc_number(x))

    print("开始处理目录...")
    total = len(mc_directories)
    if parallel and total > 1:
        # 默认进程数：min(8, CPU) 避免压垮共享盘
        if not workers or workers < 1:
            try:
                cpu = os.cpu_count() or 2
            except Exception:
                cpu = 2
            workers = min(8, cpu)

        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _process_single_mc_dir,
                    mc_dir,
                    selected_items,
                    temperature,
                    selected_units,
                    parse_warnings,
                )
                for mc_dir in mc_directories
            ]
            from tqdm import tqdm as _tqdm
            for fut in _tqdm(as_completed(futures), total=total, desc="Processing", unit="dir"):
                try:
                    res = fut.result()
                    if res:
                        all_results.append(res)
                except Exception as e:
                    # 异常兜底
                    pass
    else:
        # 串行回退
        from tqdm import tqdm as _tqdm
        with _tqdm(total=total, desc="Processing", unit="dir") as pbar:
            for mc_dir in mc_directories:
                try:
                    res = _process_single_mc_dir(mc_dir, selected_items, temperature, selected_units, parse_warnings)
                    if res:
                        all_results.append(res)
                except Exception as e:
                    print(f"处理目录时出错 {mc_dir}: {str(e)}")
                pbar.update(1)

    # 最终按mc编号排序
    all_results.sort(key=lambda x: x['MC_Number'])

    # 输出统计信息
    has_output_files = len([r for r in all_results if r['File Path']])
    no_output_files = len([r for r in all_results if not r['File Path']])
    done_status = len([r for r in all_results if r.get('Status') == 'Done'])
    failed_status = len([r for r in all_results if r.get('Status') == 'Failed'])
    running_status = len([r for r in all_results if r.get('Status') == 'Running'])
    unknown_status = len([r for r in all_results if r.get('Status') == 'Unknown'])
    
    # 统计warnings标记的任务数量
    warnings_stats = {
        'failed': len([r for r in all_results if 'failed' in r.get('warnings', [])]),
        'running': len([r for r in all_results if 'running' in r.get('warnings', [])]),
        'not_started': len([r for r in all_results if 'not_started' in r.get('warnings', [])]),
        'no_output': len([r for r in all_results if 'no_output' in r.get('warnings', [])])
    }
    
    print(f"\n处理总结:")
    print(f"总计mc目录数: {len(all_results)}")
    print(f"有输出文件的目录: {has_output_files}")
    print(f"无输出文件的目录: {no_output_files}")
    print(f"Done状态目录: {done_status}")
    print(f"Failed状态目录: {failed_status}")
    print(f"Running状态目录: {running_status}")
    print(f"Unknown状态目录: {unknown_status}")
    print(f"\n警告处理标记统计:")
    print(f"failed标记任务: {warnings_stats['failed']} 个")
    print(f"running标记任务: {warnings_stats['running']} 个")
    print(f"not_started标记任务: {warnings_stats['not_started']} 个")
    print(f"no_output标记任务: {warnings_stats['no_output']} 个")
    print(f"\n💡 提示: 可以使用警告处理模式来重新处理这些未完成的任务")
    print(f"   - 使用 warning_processor.py 选择相应的警告类型进行处理")

    return all_results

def _prefer_existing_mc_dir(base_path, index: int) -> str:
    """返回最合适状态的mc目录（优先：__done > __failed > __running > 无后缀）。若都不存在，则返回不带后缀的占位路径。"""
    candidates = [
        os.path.join(base_path, f"mc{index}__done"),
        os.path.join(base_path, f"mc{index}__failed"),
        os.path.join(base_path, f"mc{index}__running"),
        os.path.join(base_path, f"mc{index}"),
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return candidates[-1]

def _read_framework_from_simulation_input(mc_dir: str) -> str:
    try:
        sim = os.path.join(mc_dir, 'simulation.input')
        if os.path.exists(sim):
            with open(sim, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if 'FrameworkName' in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            return parts[-1]
    except Exception:
        pass
    return ''

def find_and_process_files_aligned_to_csv(base_path, selected_items, output_format='excel', temperature=None, selected_units=None, parse_warnings=True, config_path=None):
    """
    基于配置中的CSV进行对齐提取：
    - 行数严格等于 CSV 基线的条目数（避免后续数据对齐错位）
    - 每一行按 CSV 顺序对应 mc1, mc2, ...
    - 若无输出文件，保留地址（mc目录或占位路径）与框架名，其他留空，并标注warnings
    """
    # 读取配置
    csv_file = None
    framework_col = None
    try:
        cfg = None
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        if not cfg:
            # 尝试默认位置
            for p in [os.path.join(os.getcwd(), '.raspa_tools', 'config.yaml'), os.path.join(os.getcwd(), 'config.yaml')]:
                if os.path.exists(p):
                    with open(p, 'r', encoding='utf-8') as f:
                        cfg = yaml.safe_load(f) or {}
                        config_path = p
                        break
        calc = (cfg or {}).get('calculation', {})
        csv_file = calc.get('csv_file_path')
        framework_col = calc.get('framework_column')
    except Exception:
        pass

    if not csv_file or not framework_col:
        print('未能从配置读取 csv_file_path/framework_column，回退到目录扫描模式。')
        return find_and_process_files_high_throughput(base_path, selected_items, output_format, temperature, selected_units, parse_warnings, parallel=False, workers=None)

    if not os.path.exists(csv_file):
        print(f"基线CSV不存在: {csv_file}，回退到目录扫描模式。")
        return find_and_process_files_high_throughput(base_path, selected_items, output_format, temperature, selected_units, parse_warnings, parallel=False, workers=None)

    # 读取基线CSV
    try:
        df = pd.read_csv(csv_file, encoding='utf-8-sig')
    except Exception as e:
        print(f"读取基线CSV失败: {e}，回退到目录扫描模式。")
        return find_and_process_files_high_throughput(base_path, selected_items, output_format, temperature, selected_units, parse_warnings, parallel=False, workers=None)

    if framework_col not in df.columns:
        print(f"基线CSV缺少列: {framework_col}，回退到目录扫描模式。")
        return find_and_process_files_high_throughput(base_path, selected_items, output_format, temperature, selected_units, parse_warnings, parallel=False, workers=None)

    frameworks = df[framework_col].tolist()
    results = []

    # 进度条开关（遵循配置 performance.show_progress，默认True）
    show_progress = True
    try:
        show_progress = (cfg or {}).get('performance', {}).get('show_progress', True)
    except Exception:
        pass
    pbar = None
    if show_progress:
        try:
            from tqdm import tqdm as _tqdm
            pbar = _tqdm(total=len(frameworks), desc="Processing", unit="row")
        except Exception:
            pbar = None

    for i, fw in enumerate(frameworks, start=1):
        mc_dir = _prefer_existing_mc_dir(base_path, i)
        out_file = find_output_file_in_mc_dir(mc_dir) if os.path.isdir(mc_dir) else None

        row = {
            'MC_Number': i,
            'File Path': mc_dir,
            'Framework Name': '' if pd.isna(fw) else fw,
            'warnings': [],
            'MC_Directory': os.path.basename(mc_dir),
        }

        dname = os.path.basename(mc_dir)
        if dname.endswith('__done'):
            row['Status'] = 'Done'
        elif dname.endswith('__failed'):
            row['Status'] = 'Failed'
            row['warnings'] = ['failed']
        elif dname.endswith('__running'):
            row['Status'] = 'Running'
            row['warnings'] = ['running']
        else:
            row['Status'] = 'Unknown'
            row['warnings'] = ['not_started']

        if out_file:
            parsed = process_output_file(
                out_file,
                i,
                selected_items,
                temperature,
                selected_units,
                parse_warnings=parse_warnings,
            )
            if parsed:
                parsed['Framework Name'] = row['Framework Name']
                parsed['MC_Directory'] = row['MC_Directory']
                parsed['Status'] = row['Status']
                if row['warnings']:
                    if not parsed.get('warnings'):
                        parsed['warnings'] = row['warnings']
                    else:
                        parsed['warnings'].extend(row['warnings'])
                results.append(parsed)
                continue

        if not row['Framework Name'] and os.path.isdir(mc_dir):
            row['Framework Name'] = _read_framework_from_simulation_input(mc_dir) or ''

        if '__done' in dname and 'no_output' not in row['warnings'] and row['Status'] == 'Done':
            row['warnings'] = ['no_output']

        for item in selected_items:
            if item == 'Surface_Area':
                row['Surface_Area_m2_g'] = ''
                row['Surface_Area_m2_cm3'] = ''
            elif item == 'adsorption_heat_infinite_dilution':
                row['total_energy_value'] = ''
                row['adsorption_heat_infinite_dilution'] = ''
            elif item in ['absolute_adsorption', 'excess_adsorption']:
                pass
            else:
                row[item] = ''

        results.append(row)
        if pbar:
            pbar.update(1)

    if pbar:
        pbar.close()
    results.sort(key=lambda x: x.get('MC_Number', 0))
    return results

def _scan_mc_framework_map(base_path: str):
    """扫描 base_path 下所有 mc 目录，构建 framework -> 条目列表 映射。
    条目: { 'mc_dir': str, 'status': str, 'out_file': Optional[str], 'framework': str }
    framework 获取优先级：output文件名解析 > simulation.input 中 FrameworkName。
    """
    mc_dirs = find_all_mc_directories(base_path)
    fmap = {}
    for mc_dir in mc_dirs:
        dname = os.path.basename(mc_dir)
        if dname.endswith('__done'):
            status = 'Done'
        elif dname.endswith('__failed'):
            status = 'Failed'
        elif dname.endswith('__running'):
            status = 'Running'
        else:
            status = 'Unknown'

        out_file = find_output_file_in_mc_dir(mc_dir)
        framework = ''
        # 从输出文件名解析框架名（若可行）
        if out_file:
            try:
                # 复用已有的工具函数（若存在），否则用文件名分割法
                try:
                    framework = extract_framework_name_from_filepath(out_file)  # type: ignore
                except Exception:
                    pass
                if not framework:
                    name = os.path.basename(out_file)
                    if name.lower().startswith('output_'):
                        name = name[7:]
                    parts = name.split('_')
                    if len(parts) >= 3 and parts[-1].lower().endswith('.data'):
                        parts[-1] = parts[-1][:-5]
                    if len(parts) >= 3:
                        framework = '_'.join(parts[:-2])
            except Exception:
                framework = ''
        # 回退：simulation.input
        if not framework:
            framework = _read_framework_from_simulation_input(mc_dir) or ''

        item = {
            'mc_dir': mc_dir,
            'status': status,
            'out_file': out_file,
            'framework': framework,
        }
        fmap.setdefault(framework, []).append(item)

    return fmap

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

def _normalize_fw(s):
    return (s or '').strip()

def find_and_process_files_by_csv_template(base_path, selected_items, output_format='excel', temperature=None, selected_units=None, parse_warnings=True, config_path=None):
    """
    以 config.calculation.csv_file_path 为模板进行提取：
    - 顺序与 csv_file_path 中 framework_column 完全一致
    - 针对每个框架匹配 output_directory 中的 mc 目录（按框架名匹配，而非按行号映射）
    - 没有/报错的就留空并打标记（not_found / no_output / failed / running）
    """
    # 读取配置
    csv_file = None
    framework_col = None
    try:
        cfg = None
        # 显式配置优先
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        # CWD向上搜索
        if not cfg:
            for p in _config_search_paths(os.getcwd()):
                if os.path.exists(p):
                    with open(p, 'r', encoding='utf-8') as f:
                        cfg = yaml.safe_load(f) or {}
                        config_path = p
                        break
        calc = (cfg or {}).get('calculation', {})
        csv_file = calc.get('csv_file_path')
        framework_col = calc.get('framework_column')
    except Exception:
        pass

    if not csv_file or not framework_col or not os.path.exists(csv_file):
        print('按模板对齐模式：未能读取 csv_file_path/framework_column 或 CSV 不存在，回退到目录扫描模式。')
        return find_and_process_files_high_throughput(base_path, selected_items, output_format, temperature, selected_units, parse_warnings, parallel=False, workers=None)

    # 基线 CSV
    df = pd.read_csv(csv_file, encoding='utf-8-sig')
    if framework_col not in df.columns:
        print(f"基线CSV缺少列: {framework_col}，回退到目录扫描模式。")
        return find_and_process_files_high_throughput(base_path, selected_items, output_format, temperature, selected_units, parse_warnings, parallel=False, workers=None)

    fw_list = [ _normalize_fw(x) for x in df[framework_col].tolist() ]

    # 扫描 output_directory 下的 framework -> items 映射
    fmap = _scan_mc_framework_map(base_path)
    # 额外构建简化键映射（去掉常见后缀的宽松匹配）
    def simple_key(s):
        s = _normalize_fw(s)
        return s.replace('.cif','')
    loose_index = {}
    for k, items in fmap.items():
        loose_index.setdefault(simple_key(k), []).append(items)

    results = []
    # 进度条开关（遵循配置 performance.show_progress，默认True）
    show_progress = True
    try:
        show_progress = (cfg or {}).get('performance', {}).get('show_progress', True)
    except Exception:
        pass
    pbar = None
    if show_progress:
        try:
            from tqdm import tqdm as _tqdm
            pbar = _tqdm(total=len(fw_list), desc="Processing", unit="row")
        except Exception:
            pbar = None

    for i, fw in enumerate(fw_list, start=1):
        chosen = None
        # 严格匹配
        if fw in fmap:
            chosen = _best_item_for_framework(fmap[fw])
        if not chosen:
            # 宽松匹配：去掉 .cif 后缀后相等，或 startswith/endswith
            skey = simple_key(fw)
            if skey in loose_index:
                # loose_index 存储的是列表的列表
                flat = []
                for lst in loose_index[skey]:
                    flat.extend(lst)
                chosen = _best_item_for_framework(flat)
            if not chosen:
                # 遍历查找开头/包含关系
                for k, items in fmap.items():
                    if not k:
                        continue
                    kk = simple_key(k)
                    if kk == skey or kk.startswith(skey) or skey.startswith(kk):
                        chosen = _best_item_for_framework(items)
                        if chosen:
                            break

        # 构造行
        if chosen and chosen.get('out_file'):
            parsed = process_output_file(
                chosen['out_file'],
                i,
                selected_items,
                temperature,
                selected_units,
                parse_warnings=parse_warnings,
            )
            if parsed:
                parsed['Framework Name'] = fw
                parsed['MC_Directory'] = os.path.basename(chosen['mc_dir'])
                parsed['Status'] = chosen['status']
                results.append(parsed)
                continue

        # 占位逻辑
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

        for item in selected_items:
            if item == 'Surface_Area':
                row['Surface_Area_m2_g'] = ''
                row['Surface_Area_m2_cm3'] = ''
            elif item == 'adsorption_heat_infinite_dilution':
                row['total_energy_value'] = ''
                row['adsorption_heat_infinite_dilution'] = ''
            elif item in ['absolute_adsorption', 'excess_adsorption']:
                pass
            else:
                row[item] = ''

        results.append(row)
        if pbar:
            pbar.update(1)

    if pbar:
        pbar.close()
    return results

def find_output_files(base_path):
    """查找目录中的所有output文件（通用版本）"""
    output_files = []
    print("执行通用文件搜索...")

    # 查找所有名为'Output'的目录
    for root, dirs, files in os.walk(base_path):
        # 检查是否有名为'output'的文件
        if 'output' in files or 'Output' in files or 'OUTPUT' in files:
            if 'output' in files:
                output_files.append((os.path.join(root, 'output'), root))
            elif 'Output' in files:
                output_files.append((os.path.join(root, 'Output'), root))
            elif 'OUTPUT' in files:
                output_files.append((os.path.join(root, 'OUTPUT'), root))

        # 检查System_0目录下的.data文件
        if os.path.basename(root) == 'Output' or os.path.basename(root) == 'output':
            system_dir = os.path.join(root, 'System_0')
            if os.path.exists(system_dir):
                for file in os.listdir(system_dir):
                    if file.endswith('.data'):
                        output_files.append((os.path.join(system_dir, file), root))

    print(f"找到 {len(output_files)} 个输出文件")
    return output_files

def find_and_process_files(base_path, selected_items, temperature=None, selected_units=None, parse_warnings=True):
    """查找并处理所有输出文件（通用版本）"""
    all_results = []

    print("开始通用数据提取...")
    # 查找所有output文件
    output_files = find_output_files(base_path)

    if not output_files:
        print("在指定目录中未找到输出文件。")
        return []

    print("处理文件...")
    # 使用tqdm显示处理进度
    with tqdm(total=len(output_files), desc="Processing", unit="file") as pbar:
        for file_path, parent_dir in output_files:
            try:
                # 从文件路径中提取文件夹信息
                parent_folder = os.path.basename(parent_dir)

                # 尝试从文件夹名称中提取编号
                folder_num = extract_number_from_string(parent_folder)
                if folder_num is None:
                    folder_num = len(all_results) + 1  # 如果没有编号，使用递增的数字

                # 处理文件
                results = process_output_file(file_path, folder_num, selected_items, temperature, selected_units, parse_warnings=parse_warnings)
                if results:
                    all_results.append(results)
            except Exception as e:
                print(f"处理文件时出错 {file_path}: {str(e)}")

            pbar.update(1)

    # 输出统计信息
    print(f"\n处理总结")
    print(f"总计处理文件数: {len(all_results)}")

    return all_results

def extract_number_from_string(s):
    """从字符串中提取数字并返回整数形式"""
    match = re.search(r'(\d+)', s)
    if match:
        return int(match.group(1))
    else:
        return None

def save_results_to_file(results, selected_items=None, output_file='extracted_data.xlsx', format_type='excel'):
    """保存提取的数据到文件（支持Excel和CSV格式）"""
    try:
        # 将结果转换为数据行
        data_rows = []

        for result in results:
            # 初始化行数据，按照新的顺序
            row = {
                'File Path': result.get('File Path', ''),
                'Framework Name': result.get('Framework Name', ''),
                'Warnings': '; '.join(result.get('warnings', [])) if result.get('warnings') else '',
            }

            # 添加其他数据
            for key, value in result.items():
                # 跳过已处理的字段
                if key in ['MC_Number', 'MC_Directory', 'Status', 'Framework Name', 'File Path', 'warnings']:
                    continue

                # 如果是字典，展开字典的键值对
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        row[f"{key}_{sub_key}"] = sub_value
                else:
                    row[key] = value

            data_rows.append(row)

        # 创建DataFrame
        df = pd.DataFrame(data_rows)

        if df.empty:
            print("没有数据可保存")
            return False

        # 重新排列列顺序，按照要求的顺序
        columns = ['File Path', 'Framework Name', 'Warnings']

        # 添加基本参数列
        basic_columns = ['pressure', 'He_void_fraction', 'Framework_density']
        for col in basic_columns:
            if col in df.columns:
                columns.append(col)

        # 添加表面积列
        surface_area_columns = [col for col in df.columns if 'Surface_Area' in col]
        columns.extend(sorted(surface_area_columns))

        # 添加吸附量列
        adsorption_columns = [col for col in df.columns if '_absolute_' in col or '_excess_' in col]
        columns.extend(sorted(adsorption_columns))

        # 添加能量值列
        energy_columns = [col for col in df.columns if 'total_energy_value' in col]
        columns.extend(sorted(energy_columns))

        # 添加吸附热和亨利系数列
        other_columns = [col for col in df.columns if '_adsorption_heat' in col or '_henry_coefficient' in col]
        columns.extend(sorted(other_columns))

        # 添加其他列
        remaining_columns = [col for col in df.columns if col not in columns]
        columns.extend(remaining_columns)

        # 重新排序列
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
        print(f"\n保存数据时出错: {str(e)}")
        traceback.print_exc()
        return False

def save_warnings_to_excel(results, output_file='warnings.xlsx'):
    """将warnings数据单独保存到Excel文件"""
    warning_rows = []

    for result in results:
        if result.get('warnings'):  # 只处理有warnings的结果
            row = {
                'File Path': result.get('File Path', ''),
                'Framework Name': result.get('Framework Name', ''),
                'Warnings': '; '.join(result['warnings'])
            }
            warning_rows.append(row)

    if warning_rows:
        df = pd.DataFrame(warning_rows)
        df.to_excel(output_file, index=False)
        print(f"警告信息已保存到 '{output_file}'")
        print(f"在 {len(warning_rows)} 个目录中发现警告")
    else:
        print("所有目录中均未发现警告")

def get_simulation_info(file_path):
    """
    从File Path列中提取模拟文件名
    例如：从路径中提取 'output_OKUJOV_clean_pacman_2.2.2_353.000000_101300.data'
    """
    try:
        # 提取文件名部分
        return os.path.basename(file_path)
    except Exception as e:
        print(f"解析文件路径时出错: {str(e)}")
        return None

def update_existing_results(original_excel, supplement_excel, output_file='updated_data.xlsx'):
    """
    更新已有的Excel数据文件
    """
    try:
        # 读取两个Excel文件
        df_original = pd.read_excel(original_excel)
        df_supplement = pd.read_excel(supplement_excel)

        # 为两个DataFrame添加模拟信息列（提取文件名）
        df_original['simulation_info'] = df_original['File Path'].apply(get_simulation_info)
        df_supplement['simulation_info'] = df_supplement['File Path'].apply(get_simulation_info)

        updated_folders = []  # 记录更新的文件夹
        added_folders = []    # 记录新增的文件夹
        not_found = []       # 记录未找到匹配的补充数据

        # 遍历补充数据
        for _, row in df_supplement.iterrows():
            sim_info = row['simulation_info']
            if not sim_info:
                print(f"警告：无法从文件路径解析文件名：{row['File Path']}")
                continue

            # 检查是否存在匹配的行（通过文件名完全匹配）
            mask = df_original['simulation_info'] == sim_info
            if mask.any():
                # 更新已存在的数据
                for column in df_supplement.columns:
                    if column in df_original.columns and column not in ['simulation_info']:
                        df_original.loc[mask, column] = row[column]
                updated_folders.append(row.get('Framework Name', ''))
            else:
                # 添加新行
                new_row = pd.DataFrame([row])
                df_original = pd.concat([df_original, new_row], ignore_index=True)
                added_folders.append(row.get('Framework Name', ''))
                not_found.append(sim_info)

        # 删除临时的模拟信息列
        df_original = df_original.drop('simulation_info', axis=1)

        # 保存更新后的数据
        df_original.to_excel(output_file, index=False)

        # 生成更新报告
        print("\n更新报告:")
        if updated_folders:
            print(f"更新的框架: {sorted(updated_folders)}")
            print(f"共更新 {len(updated_folders)} 个框架")
        if added_folders:
            print(f"新增的框架: {sorted(added_folders)}")
            print(f"共新增 {len(added_folders)} 个框架")
        if not_found:
            print("\n未找到匹配的模拟数据:")
            for info in not_found:
                print(f"- {info}")

        return True

    except Exception as e:
        print(f"更新数据时发生错误: {str(e)}")
        return False

def _config_search_paths(start_dir: str):
    """从 start_dir 向上逐级搜索可能的配置路径。"""
    paths = []
    cur = os.path.abspath(start_dir)
    # 向上搜索 .raspa_tools/config.yaml 和 config.yaml
    while True:
        paths.append(os.path.join(cur, '.raspa_tools', 'config.yaml'))
        paths.append(os.path.join(cur, 'config.yaml'))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return paths

def _load_config(config_path=None):
    """加载配置，返回 (config_dict, used_path)。优先顺序：显式 -> 从CWD向上搜索。"""
    candidates = []
    if config_path:
        candidates.append(config_path)
    candidates.extend(_config_search_paths(os.getcwd()))
    for p in candidates:
        try:
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}, p
        except Exception:
            continue
    return {}, None

def _default_base_path_from_config(cfg: dict):
    """根据配置推导默认提取目录 base_path: environment.work_dir + calculation.output_directory。回退到CWD。"""
    try:
        work_dir = cfg.get('environment', {}).get('work_dir')
        out_dir = cfg.get('calculation', {}).get('output_directory')
        if work_dir and out_dir:
            return os.path.join(work_dir, out_dir)
    except Exception:
        pass
    return os.getcwd()

def main():
    print("=== RASPA数据提取工具 ===")
    print("该工具将从指定目录中提取所有output文件的数据")

    # 预加载配置以给出更合理的默认 base_path
    cfg, cfg_path = _load_config()
    suggested_base = _default_base_path_from_config(cfg)

    # 获取目录路径（默认使用配置中的 work_dir/output_directory）
    base_path = input(f"请输入要提取数据的目录路径 (默认: {suggested_base}): ").strip()
    if not base_path:
        base_path = suggested_base

    if not os.path.exists(base_path):
        print(f"错误: 目录 '{base_path}' 不存在")
        return

    # 检测计算模式
    print("\n检测计算模式...")
    mc_dirs = []
    for root, dirs, files in os.walk(base_path):
        for dir_name in dirs:
            if re.match(r'mc\d+', dir_name):
                mc_dirs.append(dir_name)
        if mc_dirs:
            break  # 只检查第一层目录

    is_high_throughput = len(mc_dirs) > 0
    
    if is_high_throughput:
        print(f"✓ 检测到高通量计算模式（找到 {len(mc_dirs)} 个mc目录）")
        print("将按mc1, mc2, mc3...的顺序提取数据，包括没有输出文件的目录")
        print("✓ 将基于配置中的 csv_file_path / framework_column 对齐输出行数")
    else:
        print("✓ 检测到通用模式")

    # 选择输出格式
    print("\n选择输出格式:")
    print("1. Excel格式 (.xlsx)")
    print("2. CSV格式 (.csv)")
    format_choice = input("请选择输出格式 (1/2, 默认为Excel): ").strip()
    
    if format_choice == '2':
        output_format = 'csv'
        default_filename = 'raspa_results.csv'
    else:
        output_format = 'excel'
        default_filename = 'raspa_results.xlsx'

    # 选择要提取的数据项
    options_dict = {
        '1': 'pressure',
        '2': 'He_void_fraction',
        '3': 'Surface_Area',
        '4': 'Framework_density',
        '5': 'absolute_adsorption',
        '6': 'excess_adsorption',
        '7': 'adsorption_heat',
        '8': 'adsorption_heat_infinite_dilution',
        '9': 'henry_coefficient'
    }

    # 默认选择所有项
    selected_items = list(options_dict.values())

    # 询问是否自定义选择
    custom_select = input("\n是否自定义选择要提取的数据项? (默认提取所有数据) (y/n): ").strip().lower()

    if custom_select == 'y':
        while True:
            print("\n请选择要提取的数据项（输入对应的数字，用逗号分隔）：")
            print("1. Pressure (压力)")
            print("2. He Void Fraction (氦空隙率)")
            print("3. Surface Area (比表面积)")
            print("4. Framework Density (框架密度)")
            print("5. Absolute Adsorption (绝对吸附量)")
            print("6. Excess Adsorption (超额吸附量)")
            print("7. Adsorption Heat (吸附热)")
            print("8. Adsorption Heat at Infinite Dilution (无限稀释吸附热)")
            print("9. Henry Coefficient (亨利系数)")
            selected_numbers = input("您的选择：").strip()

            if not selected_numbers:  # 如果用户没有输入，默认选择所有项
                selected_items = list(options_dict.values())
                break

            selected_items = []
            invalid_inputs = False
            for num in selected_numbers.split(','):
                num = num.strip()
                if num in options_dict:
                    selected_items.append(options_dict[num])
                else:
                    print(f"无效的选项: {num}")
                    invalid_inputs = True

            if invalid_inputs or not selected_items:
                print("请重新输入有效的选项数字。\n")
                continue
            else:
                break

    print("\n将提取以下数据项：")
    for item in selected_items:
        print(f"- {item}")

    # 选择单位（针对吸附量），并设置温度（如果选择了无限稀释吸附热）
    selected_units = None
    if 'absolute_adsorption' in selected_items or 'excess_adsorption' in selected_items:
        selected_units = {}
        unit_options = {
            '1': 'mol/kg',
            '2': 'cm^3/g',
            '3': 'mg/g',
            '4': 'cm^3/cm^3',
        }
        if 'absolute_adsorption' in selected_items:
            print("\n绝对吸附量单位选择:")
            print("1. mol/kg    2. cm^3/g    3. mg/g    4. cm^3/cm^3")
            choice = input("请选择绝对吸附量单位 (默认: 2): ").strip()
            selected_units['absolute_adsorption'] = unit_options.get(choice, 'cm^3/g')
        if 'excess_adsorption' in selected_items:
            print("\n超额吸附量单位选择:")
            print("1. mol/kg    2. cm^3/g    3. mg/g    4. cm^3/cm^3")
            choice = input("请选择超额吸附量单位 (默认: 2): ").strip()
            selected_units['excess_adsorption'] = unit_options.get(choice, 'cm^3/g')

    # 设置温度（如果选择了无限稀释吸附热）
    temperature = None
    if 'adsorption_heat_infinite_dilution' in selected_items:
        print("\n检测到选择了无限稀释吸附热计算")
        print("注意：将会提取Total energy的原始值，并根据您设置的温度计算吸附热")
        temp_input = input("请输入计算温度 (K，默认为300): ").strip()
        
        if temp_input:
            try:
                temperature = float(temp_input)
                print(f"设置计算温度为: {temperature} K")
            except ValueError:
                print("温度输入无效，将使用默认温度 300 K")
                temperature = 300.0
        else:
            temperature = 300.0
            print("使用默认温度: 300 K")
        
        print(f"计算公式: ΔH = (Total_energy - {temperature}) × 8.314462618 / 1000 [kJ/mol]")

    # 设置输出文件名
    output_file = input(f"\n请输入输出文件名 (默认为 '{default_filename}'): ").strip()
    if not output_file:
        output_file = default_filename
    
    # 确保文件扩展名正确
    if output_format == 'csv' and not output_file.endswith('.csv'):
        if output_file.endswith('.xlsx'):
            output_file = output_file[:-5] + '.csv'
        else:
            output_file += '.csv'
    elif output_format == 'excel' and not output_file.endswith('.xlsx'):
        if output_file.endswith('.csv'):
            output_file = output_file[:-4] + '.xlsx'
        else:
            output_file += '.xlsx'

    # 是否解析输出文件内部warnings（略慢，默认否）
    parse_warnings = False
    if 'y' == input("\n是否解析输出文件内部的警告信息? (较慢, 默认n) (y/n): ").strip().lower():
        parse_warnings = True

    # 开始提取数据
    print(f"\n开始从 {base_path} 提取数据...")
    
    parallel = False
    workers = None
    if is_high_throughput:
        # 高通量模式：优先使用“按模板(配置CSV中framework_column)匹配”的提取，确保按框架名映射
        results = find_and_process_files_by_csv_template(
            base_path,
            selected_items,
            output_format,
            temperature,
            selected_units,
            parse_warnings=parse_warnings,
            config_path=cfg_path,
        )
    else:
        results = find_and_process_files(base_path, selected_items, temperature, selected_units, parse_warnings=parse_warnings)

    if results:
        save_results_to_file(results, selected_items, output_file, output_format)
        
        # 如果是Excel格式，同时保存警告文件
        if output_format == 'excel':
            warnings_file = 'warnings_' + output_file
            save_warnings_to_excel(results, warnings_file)
            print(f"警告信息已保存到 '{warnings_file}'")
        
        print(f"\n✓ 数据提取成功。共处理 {len(results)} 个目录。")
        print(f"✓ 结果已保存到 '{output_file}'")
        
        if is_high_throughput:
            print(f"✓ 数据已按mc目录编号顺序排列，与配置CSV完全对齐")
            print(f"✓ 包括没有输出文件/未存在的目录（保留地址或占位信息）")
    else:
        print("\n✗ 未找到数据文件或所有处理失败。")

if __name__ == "__main__":
    main()
