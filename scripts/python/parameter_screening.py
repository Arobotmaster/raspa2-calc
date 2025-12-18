#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 以下为用户提供的parameter_screening.py主逻辑脚本
# ...（完整内容见上一轮用户消息，已省略注释）...

import os
import sys
import json
import pandas as pd
import logging
import argparse
import shutil
import traceback
import itertools
import subprocess
import re
from pathlib import Path

# 导入calculate_params模块中的必要函数
from calculate_params import process_structure_file, get_cif_cell_parameters

# 尝试导入yaml处理配置文件
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_config():
    """加载配置文件"""
    if not HAS_YAML:
        return None

    config_paths = [
        "config.yaml",
        ".raspa_tools/config.yaml",
        os.path.join(os.path.dirname(__file__), "../../config.yaml"),
        os.path.join(os.path.expanduser("~"), "raspa2-calc", ".raspa_tools", "config.yaml")
    ]

    for config_file in config_paths:
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    logger.info(f"配置文件已加载: {config_file}")
                    return config
            except Exception as e:
                logger.warning(f"配置文件加载失败: {e}")

    return None

def setup_arg_parser():
    """设置命令行参数解析器"""
    parser = argparse.ArgumentParser(description='RASPA参数筛选工具')

    # 添加位置参数，用于接收CSV文件路径和列号
    parser.add_argument("csv_file", type=str, nargs='?', help="CSV文件路径")
    parser.add_argument("column_number", type=str, nargs='?', help="包含框架名称的列号")

    # 原有的命名参数
    parser.add_argument('--cif-dir', type=str, help='CIF文件目录路径')
    parser.add_argument('--molecule', type=str, help='模拟分子名称')
    parser.add_argument('--template', type=str, help='自定义simulation.input模板路径')

    # 添加作业系统自动检测选项，不区分大小写
    parser.add_argument('--job-system', type=str, choices=['auto', 'slurm', 'pbs', 'local'],
                      default='auto', help='作业调度系统类型，默认自动检测')

    # 添加配置文件选项
    parser.add_argument('--config', type=str, help='配置文件路径')
    parser.add_argument('--use-config', action='store_true', help='使用配置文件中的参数（非交互模式）')

    return parser

def detect_job_system():
    """自动检测当前系统使用的作业调度系统"""
    if shutil.which('sbatch'):
        return "slurm"
    elif shutil.which('qsub'):
        return "pbs"
    else:
        return "local"

def get_job_templates(job_system):
    """根据作业系统类型获取对应的作业模板和提交命令"""
    # 统一转为小写处理
    job_system = job_system.lower()
    
    if job_system == "slurm":
        return {
            "template": "job_templates/sbatch.sh",
            "submit_cmd": "sbatch"
        }
    elif job_system == "pbs":
        return {
            "template": "job_templates/pbs.sh",
            "submit_cmd": "qsub"
        }
    else:
        return {
            "template": "job_templates/local.sh",
            "submit_cmd": "bash"
        }

def read_csv_data(csv_path, column_number):
    """读取CSV文件中的框架数据"""
    try:
        df = pd.read_csv(csv_path)

        # 显示CSV文件的列信息
        print("CSV文件的列信息：")
        for i, col in enumerate(df.columns, 1):
            print(f"     {i}  {col}")

        # 获取指定列的框架名称
        col_idx = int(column_number) - 1
        if 0 <= col_idx < len(df.columns):
            frameworks = df.iloc[:, col_idx].dropna().unique().tolist()
            logger.info(f"成功从{csv_path}第{column_number}列读取数据，共{len(frameworks)}个框架")
            return frameworks
        else:
            logger.error(f"列号{column_number}超出范围，CSV文件只有{len(df.columns)}列")
            return []
    except Exception as e:
        logger.error(f"读取CSV文件失败: {e}")
        return []

def load_void_fraction_from_csv(csv_path, framework_column, void_column):
    """从CSV文件加载空隙率数据

    Args:
        csv_path: CSV文件路径
        framework_column: 框架名称列名
        void_column: 空隙率列名

    Returns:
        dict: {框架名: 空隙率}
    """
    try:
        df = pd.read_csv(csv_path)

        if framework_column not in df.columns:
            logger.error(f"CSV文件中未找到框架列: {framework_column}")
            return {}

        if void_column not in df.columns:
            logger.error(f"CSV文件中未找到空隙率列: {void_column}")
            return {}

        # 创建框架名到空隙率的映射
        void_dict = {}
        for _, row in df.iterrows():
            framework = row[framework_column]
            void_frac = row[void_column]
            if pd.notna(framework) and pd.notna(void_frac):
                void_dict[str(framework)] = float(void_frac)

        logger.info(f"从CSV文件加载了 {len(void_dict)} 个框架的空隙率数据")
        return void_dict

    except Exception as e:
        logger.error(f"加载空隙率数据失败: {e}")
        return {}

def find_cif_file(framework_name, cif_dir):
    """查找框架对应的CIF文件，支持大小写和后缀的智能匹配"""
    # 检查直接匹配
    direct_match = os.path.join(cif_dir, f"{framework_name}.cif")
    if os.path.exists(direct_match):
        return direct_match
    
    # 检查其他可能的匹配（大小写、后缀）
    possible_patterns = [
        f"{framework_name}.cif",
        f"{framework_name}.CIF",
        f"{framework_name}",
        f"{framework_name.upper()}.cif",
        f"{framework_name.lower()}.cif"
    ]
    
    for filename in os.listdir(cif_dir):
        base_name = os.path.splitext(filename)[0]
        if base_name.lower() == framework_name.lower() or filename in possible_patterns:
            return os.path.join(cif_dir, filename)
    
    return None

def generate_parameter_combinations(param_ranges):
    """根据参数范围生成所有可能的参数组合"""
    if not param_ranges:
        return [{}]

    param_names = list(param_ranges.keys())
    param_values = [param_ranges[name] for name in param_names]

    combinations = []
    for values in itertools.product(*param_values):
        param_dict = dict(zip(param_names, values))
        combinations.append(param_dict)

    return combinations

def generate_directory_name(param_combo):
    """根据参数组合生成目录名"""
    if not param_combo:
        return "default"

    # 参数名缩写映射
    abbrev_map = {
        'CutOffVDW': 'COV',
        'CutOffChargeCharge': 'COC',
        'NumberOfCycles': 'NC',
        'NumberOfInitializationCycles': 'NIC',
        'NumberOfEquilibrationCycles': 'NEC',
        'ExternalTemperature': 'T',
        'ExternalPressure': 'P',
        'ForceField': 'FF',
        'ChargeMethod': 'CM',
        'MoleculeName': 'MOL',
        'EwaldPrecision': 'EP',
        'TranslationProbability': 'TP',
        'RotationProbability': 'RP',
        'ReinsertionProbability': 'RIP',
    }

    parts = []
    for key, value in param_combo.items():
        # 使用缩写或原名称
        abbrev = abbrev_map.get(key, key[:3].upper())
        # 格式化值
        if isinstance(value, float):
            if value >= 1000 or value < 0.01:
                value_str = f"{value:.1e}".replace('+', '')
            else:
                value_str = f"{value:.1f}".rstrip('0').rstrip('.')
        else:
            value_str = str(value)
        parts.append(f"{abbrev}_{value_str}")

    return "_".join(parts)

def count_components_in_template(template_path):
    """计算模板文件中的组分数量"""
    try:
        with open(template_path, 'r') as f:
            content = f.read()
            
        # 使用正则表达式查找所有 "Component X MoleculeName" 行
        component_pattern = r'Component\s+(\d+)\s+MoleculeName'
        components = re.findall(component_pattern, content)
        
        if components:
            return len(components)
        else:
            return 0
    except Exception as e:
        logger.error(f"读取模板文件失败: {e}")
        return 0

# ============================================================
#                    RASPA3 参数筛选支持
# ============================================================

def copy_raspa3_json_files(json_dir, output_dir, component_names=None):
    """复制 RASPA3 所需的 JSON 文件到任务目录

    Args:
        json_dir: RASPA3 JSON 文件目录（包含 force_field.json 和分子定义文件）
        output_dir: 任务输出目录
        component_names: 组件名称列表，用于确定需要复制哪些分子文件

    Returns:
        bool: 成功返回 True
    """
    try:
        # 复制 force_field.json
        ff_src = os.path.join(json_dir, "force_field.json")
        if os.path.exists(ff_src):
            shutil.copy(ff_src, output_dir)
            logger.debug(f"复制 force_field.json 到 {output_dir}")
        else:
            logger.warning(f"force_field.json 不存在: {ff_src}")

        # 复制分子定义文件
        if component_names:
            for name in component_names:
                mol_src = os.path.join(json_dir, f"{name}.json")
                if os.path.exists(mol_src):
                    shutil.copy(mol_src, output_dir)
                    logger.debug(f"复制 {name}.json 到 {output_dir}")
        else:
            # 如果未指定组件，复制所有 .json 文件（除了 simulation.json）
            for f in os.listdir(json_dir):
                if f.endswith('.json') and f != 'simulation.json':
                    shutil.copy(os.path.join(json_dir, f), output_dir)

        return True
    except Exception as e:
        logger.error(f"复制 RASPA3 JSON 文件失败: {e}")
        return False


def create_simulation_json(template_path, params, cif_path, output_path, config=None, void_fraction_csv=None):
    """根据模板和参数创建 RASPA3 simulation.json 文件

    Args:
        template_path: JSON 模板文件路径
        params: 参数字典,包含要替换的参数
        cif_path: CIF 文件路径
        output_path: 输出文件路径
        config: 配置对象
        void_fraction_csv: 空隙率数据字典

    RASPA3 参数映射:
        - CutOff / CutOffVDW -> Systems[0].CutOff
        - ExternalTemperature -> Systems[0].ExternalTemperature
        - ExternalPressure -> Systems[0].ExternalPressure
        - NumberOfCycles -> NumberOfCycles (顶层)
        - NumberOfInitializationCycles -> NumberOfInitializationCycles (顶层)
        - NumberOfEquilibrationCycles -> NumberOfEquilibrationCycles (顶层)
        - framework -> Systems[0].Name (CIF 路径)
    """
    try:
        # 读取模板文件
        with open(template_path, 'r', encoding='utf-8') as f:
            sim_config = json.load(f)

        # 获取框架名称和 CIF 路径
        framework_name = params.get('framework', '')

        # 设置 CIF 文件路径
        if cif_path and os.path.exists(cif_path):
            # 使用绝对路径或相对路径
            if config:
                cif_base = config.get('environment', {}).get('raspa3_cif_base_path', '')
                if cif_base and cif_path.startswith(cif_base):
                    # 可以使用相对路径或绝对路径
                    sim_config['Systems'][0]['Name'] = cif_path
                else:
                    sim_config['Systems'][0]['Name'] = cif_path
            else:
                sim_config['Systems'][0]['Name'] = cif_path
            logger.info(f"设置 CIF 路径: {cif_path}")

        # 计算 UnitCells（如果启用）
        auto_unit_cells = config.get('parameter_screening', {}).get('auto_unit_cells', True) if config else True
        cutoff_value = float(params.get('CutOff') or params.get('CutOffVDW') or params.get('cutoff', 12.0))

        if auto_unit_cells and cif_path and os.path.exists(cif_path):
            try:
                success, unit_cells_tuple, void_fraction = process_structure_file(
                    cif_path, cutoff_value
                )
                if success and unit_cells_tuple:
                    sim_config['Systems'][0]['NumberOfUnitCells'] = list(unit_cells_tuple)
                    logger.info(f"计算 NumberOfUnitCells: {unit_cells_tuple}")

                    # 设置空隙率
                    if void_fraction is not None:
                        sim_config['Systems'][0]['HeliumVoidFraction'] = void_fraction
                        logger.info(f"设置 HeliumVoidFraction: {void_fraction}")
            except Exception as e:
                logger.warning(f"计算 UnitCells 失败: {e}")

        # 从 CSV 获取空隙率（如果配置了）
        if void_fraction_csv and framework_name:
            vf = void_fraction_csv.get(framework_name)
            if vf is not None:
                sim_config['Systems'][0]['HeliumVoidFraction'] = vf
                logger.info(f"从 CSV 设置 HeliumVoidFraction: {vf}")

        # 替换顶层参数
        top_level_params = ['NumberOfCycles', 'NumberOfInitializationCycles',
                          'NumberOfEquilibrationCycles', 'PrintEvery', 'SimulationType']
        for param in top_level_params:
            if param in params:
                sim_config[param] = params[param]
                logger.debug(f"设置顶层参数 {param}: {params[param]}")

        # 替换 Systems[0] 参数
        system_params_map = {
            'CutOff': 'CutOff',
            'CutOffVDW': 'CutOff',  # 兼容 RASPA2 参数名
            'cutoff': 'CutOff',
            'ExternalTemperature': 'ExternalTemperature',
            'temperature': 'ExternalTemperature',
            'ExternalPressure': 'ExternalPressure',
            'pressure': 'ExternalPressure',
            'ChargeMethod': 'ChargeMethod',
            'HeliumVoidFraction': 'HeliumVoidFraction',
        }

        for param_key, json_key in system_params_map.items():
            if param_key in params:
                sim_config['Systems'][0][json_key] = params[param_key]
                logger.debug(f"设置 Systems[0].{json_key}: {params[param_key]}")

        # 写入输出文件
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(sim_config, f, indent=2, ensure_ascii=False)

        logger.info(f"成功创建 RASPA3 配置文件: {output_path}")
        return True

    except Exception as e:
        logger.error(f"创建 simulation.json 文件失败: {e}")
        logger.debug(traceback.format_exc())
        return False


def create_job_script_raspa3(param_dir, job_name, scheduler_type="slurm", conda_env="raspa3"):
    """创建 RASPA3 作业提交脚本

    Args:
        param_dir: 参数目录
        job_name: 作业名称
        scheduler_type: 调度系统类型 ('slurm', 'pbs', 或 'local')
        conda_env: RASPA3 conda 环境名称

    Returns:
        str: 脚本文件路径
    """
    script_path = os.path.join(param_dir, "job.sh")

    # conda 初始化脚本
    conda_init = '''
# 初始化 conda
if [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
fi
'''

    if scheduler_type == "slurm":
        script_content = f'''#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --hint=multithread
#SBATCH --output=%x.%j.out
#SBATCH --error=%x.%j.err

# 设置资源限制
ulimit -u 20480
ulimit -s 16384

# 设置环境变量
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
{conda_init}
# 激活 RASPA3 环境
conda activate {conda_env}

# 设置工作目录
cd {param_dir}

echo $SLURM_JOB_ID > jobid

# 运行 RASPA3
raspa3
'''
    elif scheduler_type == "pbs":
        script_content = f'''#!/bin/bash
#PBS -N {job_name}
#PBS -l nodes=1:ppn=1
#PBS -o pbs.out
#PBS -e pbs.err
#PBS -j oe

# 设置资源限制
ulimit -u 20480
ulimit -s 16384

# 设置环境变量
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
{conda_init}
# 激活 RASPA3 环境
conda activate {conda_env}

# 切换到作业目录
cd $PBS_O_WORKDIR

echo $PBS_JOBID > jobid

# 运行 RASPA3
raspa3
'''
    else:
        script_content = f'''#!/bin/bash

# 设置环境变量
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
{conda_init}
# 激活 RASPA3 环境
conda activate {conda_env}

# 切换到作业目录
cd {param_dir}

echo $$ > jobid

# 运行 RASPA3
raspa3
'''

    with open(script_path, 'w') as f:
        f.write(script_content)

    os.chmod(script_path, 0o755)
    logger.info(f"创建 RASPA3 作业脚本: {script_path}")

    return script_path


def process_parameter_combinations_raspa3(framework, cif_path, param_ranges, template_path,
                                          output_dir, job_system, config=None,
                                          void_fraction_csv=None, json_dir=None):
    """处理 RASPA3 所有参数组合并创建作业

    Args:
        framework: 框架名称
        cif_path: CIF 文件路径
        param_ranges: 参数范围字典
        template_path: JSON 模板文件路径
        output_dir: 输出目录
        job_system: 作业系统类型
        config: 配置对象
        void_fraction_csv: 空隙率数据字典
        json_dir: RASPA3 JSON 文件目录
    """
    # 生成所有参数组合
    combinations = generate_parameter_combinations(param_ranges)
    logger.info(f"框架 {framework}: 生成了 {len(combinations)} 种参数组合")

    # 创建输出主目录
    output_base_dir = os.path.join(os.getcwd(), output_dir)
    os.makedirs(output_base_dir, exist_ok=True)

    # 创建框架目录
    framework_dir = os.path.join(output_base_dir, framework)
    os.makedirs(framework_dir, exist_ok=True)

    # 获取 conda 环境名称
    conda_env = "raspa3"
    if config:
        conda_env = config.get('environment', {}).get('raspa3_conda_env', 'raspa3')

    # 获取组件名称（用于复制分子文件）
    component_names = None
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            template_data = json.load(f)
            components = template_data.get('Components', [])
            component_names = list(set(c.get('Name', '') for c in components if c.get('Name')))
    except Exception:
        pass

    # 处理每个参数组合
    jobs = []
    for combo in combinations:
        # 生成参数组合目录名
        param_dir_name = generate_directory_name(combo)
        param_dir = os.path.join(framework_dir, param_dir_name)
        os.makedirs(param_dir, exist_ok=True)

        # 复制 RASPA3 JSON 文件
        if json_dir:
            copy_raspa3_json_files(json_dir, param_dir, component_names)

        # 准备参数字典
        sim_params = combo.copy()
        sim_params['framework'] = framework

        # 创建 simulation.json 文件
        sim_json_path = os.path.join(param_dir, "simulation.json")

        if create_simulation_json(template_path, sim_params, cif_path, sim_json_path, config, void_fraction_csv):
            # 创建作业脚本
            job_name = f"{framework}_{param_dir_name}"[:63]  # SLURM 作业名限制
            job_script_path = create_job_script_raspa3(param_dir, job_name, job_system, conda_env)

            # 提交作业
            job_id = submit_job(job_script_path, job_system)
            if job_id:
                jobs.append({
                    'param_dir': param_dir,
                    'job_id': job_id,
                    'params': combo
                })
                print(f"  ✓ 作业已提交: {job_name} (ID: {job_id})")

    return jobs

# ============================================================
#                    RASPA2 参数筛选 (原有功能)
# ============================================================

def create_simulation_input(template_path, params, cif_path, output_path, config=None, void_fraction_csv=None):
    """根据模板和参数创建simulation.input文件 - 支持通用参数替换

    Args:
        template_path: 模板文件路径
        params: 参数字典,包含要替换的参数
        cif_path: CIF文件路径
        output_path: 输出文件路径
        config: 配置对象,用于获取auto_unit_cells等设置
        void_fraction_csv: 空隙率数据字典(从CSV读取)
    """
    try:
        # 读取模板文件
        with open(template_path, 'r') as f:
            template = f.read()

        # 分行处理模板文件
        lines = template.split('\n')

        # 从CIF文件计算UnitCells参数
        unit_cells = None
        void_fraction = None
        auto_unit_cells = config.get('parameter_screening', {}).get('auto_unit_cells', True) if config else True

        # 检查是否从CSV获取空隙率
        use_void_csv = config.get('calculation', {}).get('use_void_csv', False) if config else False
        framework_name = params.get('framework')

        if use_void_csv and void_fraction_csv and framework_name:
            # 从CSV字典获取空隙率
            void_fraction = void_fraction_csv.get(framework_name)
            if void_fraction is not None:
                logger.info(f"从CSV文件获取空隙率: {void_fraction}")
            else:
                logger.warning(f"CSV中未找到框架 {framework_name} 的空隙率数据")

        if cif_path and os.path.exists(cif_path) and auto_unit_cells:
            try:
                # 获取截断半径参数 - 优先从params中获取
                cutoff_value = float(params.get('CutOffVDW') or params.get('cutoff', 12.0))
                logger.info(f"使用截断半径 {cutoff_value} Å 计算UnitCells参数")

                # 准备CSV参数(如果启用)
                csv_file = None
                void_fraction_column = None
                framework_column = None

                if use_void_csv and config:
                    csv_file = config.get('calculation', {}).get('void_csv_file')
                    void_fraction_column = config.get('calculation', {}).get('void_column', 'VF')
                    framework_column = config.get('calculation', {}).get('framework_column', 'refcode')

                # 使用calculate_params模块中的函数计算UnitCells (复用高通量模式的实现)
                success, unit_cells_tuple, void_fraction_value = process_structure_file(
                    cif_path,
                    cutoff_value,
                    csv_file=csv_file,
                    void_fraction_column=void_fraction_column,
                    framework_column=framework_column
                )

                if success and unit_cells_tuple:
                    unit_cells = unit_cells_tuple
                    # 如果process_structure_file从CSV读取了空隙率,使用它
                    # 否则使用之前从void_fraction_csv字典获取的值
                    if void_fraction is None and void_fraction_value is not None:
                        void_fraction = void_fraction_value
                        logger.info(f"从CSV/CIF文件获取到空隙率: {void_fraction}")
                    logger.info(f"从CIF文件计算得到UnitCells: {unit_cells}")
                else:
                    # 备用：直接尝试使用get_cif_cell_parameters
                    cell_params = get_cif_cell_parameters(cif_path, cutoff_value)
                    if cell_params:
                        unit_cells = cell_params
                        logger.info(f"使用备选方法计算得到UnitCells: {unit_cells}")
            except Exception as e:
                logger.error(f"计算UnitCells参数失败: {e}")
                logger.debug(traceback.format_exc())

        # 处理每一行,使用通用参数替换
        for i, line in enumerate(lines):
            # 跳过空行和注释
            if not line.strip() or line.strip().startswith('#'):
                continue

            # 通用参数匹配: 参数名 + 空格 + 值
            # 匹配格式: ParameterName   Value
            match = re.match(r'^(\s*)(\w+)(\s+)(.+)$', line)
            if match:
                indent = match.group(1)
                param_name = match.group(2)
                spaces = match.group(3)
                old_value = match.group(4)

                # 检查是否需要替换此参数
                if param_name in params:
                    new_value = params[param_name]
                    lines[i] = f"{indent}{param_name}{spaces}{new_value}"
                    logger.debug(f"替换参数 {param_name}: {old_value} -> {new_value}")

            # 特殊处理: 框架名称
            if 'framework' in params and 'FrameworkName' in line:
                pattern = r'(FrameworkName\s+)(\S+)'
                match = re.search(pattern, line)
                if match:
                    prefix = match.group(1)
                    lines[i] = f"{prefix}{params['framework']}"
                    logger.debug(f"替换框架名称: {params['framework']}")

            # 特殊处理: UnitCells参数（如果已计算）
            if unit_cells and 'UnitCells' in line:
                pattern = r'(UnitCells\s+)([0-9\s]+)'
                match = re.search(pattern, line)
                if match:
                    prefix = match.group(1)
                    cells_str = f"{unit_cells[0]} {unit_cells[1]} {unit_cells[2]}"
                    lines[i] = f"{prefix}{cells_str}"
                    logger.info(f"替换UnitCells参数: {cells_str}")

            # 特殊处理: HeliumVoidFraction参数（如果已计算）
            if void_fraction is not None and 'HeliumVoidFraction' in line:
                pattern = r'(HeliumVoidFraction\s+)([0-9.e+-]+)'
                match = re.search(pattern, line)
                if match:
                    prefix = match.group(1)
                    lines[i] = f"{prefix}{void_fraction}"
                    logger.info(f"替换HeliumVoidFraction参数: {void_fraction}")

        # 重新组合处理后的行
        template = '\n'.join(lines)

        # 写入输出文件
        with open(output_path, 'w') as f:
            f.write(template)

        logger.info(f"成功创建模拟输入文件: {output_path}")
        return True
    except Exception as e:
        logger.error(f"创建simulation.input文件失败: {e}")
        logger.debug(traceback.format_exc())
        return False

def create_job_script(param_dir, job_name, scheduler_type="pbs"):
    """创建作业提交脚本

    Args:
        param_dir: 参数目录
        job_name: 作业名称
        scheduler_type: 调度系统类型 ('slurm', 'pbs', 或 'local')

    Returns:
        str: 脚本文件路径
    """
    # 创建脚本文件路径
    script_path = os.path.join(param_dir, "job.sh")
    
    # 获取RASPA目录
    raspa_dir = os.environ.get('RASPA_DIR', '')
    raspa_cmd = os.path.join(raspa_dir, "bin", "simulate")
    
    # 根据调度系统类型生成不同的脚本内容
    if scheduler_type == "slurm":
        # SLURM脚本
        script_content = f"""#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --hint=multithread
#SBATCH --output=%x.%j.out
#SBATCH --error=%x.%j.err

# 设置资源限制和线程数
ulimit -u 20480
ulimit -s 16384

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1 
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

# 设置工作目录
cd {param_dir}

echo $SLURM_JOB_ID > jobid

# 运行RASPA
{raspa_cmd}
"""
    elif scheduler_type == "pbs":
        # PBS脚本
        script_content = f"""#!/bin/bash
#PBS -N {job_name}
#PBS -l nodes=1:ppn=1
#PBS -o pbs.out
#PBS -e pbs.err
#PBS -j oe

# 设置资源限制和线程数
ulimit -u 20480
ulimit -s 16384

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1 
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

# 切换到作业提交的目录
cd $PBS_O_WORKDIR

echo $PBS_JOBID > jobid

# 运行RASPA
{raspa_cmd}
"""
    else:
        # 本地脚本
        script_content = f"""#!/bin/bash

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1 
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

# 切换到作业目录
cd {param_dir}

echo $$ > jobid

# 运行RASPA
{raspa_cmd}
"""

    # 写入脚本文件
    with open(script_path, 'w') as f:
        f.write(script_content)

    # 设置执行权限
    os.chmod(script_path, 0o755)
    logger.info(f"创建作业脚本: {script_path}")

    return script_path

def submit_job(script_path, scheduler_type="pbs"):
    """提交作业

    Args:
        script_path: 脚本文件路径
        scheduler_type: 调度系统类型 ('slurm', 'pbs', 或 'local')

    Returns:
        str: 作业ID或None（如果提交失败）
    """
    try:
        # 保存当前目录
        original_dir = os.getcwd()

        # 切换到脚本所在目录
        script_dir = os.path.dirname(script_path)
        os.chdir(script_dir)
        script_name = os.path.basename(script_path)

        # 根据调度系统类型提交作业
        if scheduler_type == "slurm":
            # 使用SLURM提交作业
            result = subprocess.run(["sbatch", script_name],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  check=False)

            # 处理结果
            if result.returncode == 0:
                # 从输出中提取作业ID
                output = result.stdout.decode('utf-8').strip()
                # SLURM输出格式通常是 "Submitted batch job 123456"
                job_id = output.split()[-1] if output else "unknown"
                logger.info(f"作业提交成功，ID: {job_id}")
                # 将作业ID写入文件
                with open(os.path.join(script_dir, "jobid"), 'w') as f:
                    f.write(job_id)
                return job_id
            else:
                error = result.stderr.decode('utf-8').strip()
                logger.error(f"作业提交失败: {error}")
                return None

        elif scheduler_type == "pbs":
            # 使用PBS提交作业
            result = subprocess.run(["qsub", script_name],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  check=False)

            # 处理结果
            if result.returncode == 0:
                job_id = result.stdout.decode('utf-8').strip()
                logger.info(f"作业提交成功，ID: {job_id}")
                # 将作业ID写入文件
                with open(os.path.join(script_dir, "jobid"), 'w') as f:
                    f.write(job_id)
                return job_id
            else:
                error = result.stderr.decode('utf-8').strip()
                logger.error(f"作业提交失败: {error}")
                return None
        else:
            # 本地模式，直接在后台运行
            process = subprocess.Popen(["bash", script_name],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)

            # 将进程ID写入文件
            job_id = str(process.pid)
            with open(os.path.join(script_dir, "jobid"), 'w') as f:
                f.write(job_id)

            logger.info(f"本地作业已启动，进程ID: {job_id}")
            return job_id

    except Exception as e:
        logger.error(f"提交作业时出错: {e}")
        logger.debug(traceback.format_exc())
        return None
    finally:
        # 返回原始目录
        os.chdir(original_dir)

def parse_number_list(input_str):
    """解析数字列表，支持空格或逗号作为分隔符"""
    if not input_str.strip():
        return []
    
    # 先替换非标准空格为普通空格
    input_str = re.sub(r'\s', ' ', input_str)
    
    # 预处理：将连续多个空格替换为单个空格
    input_str = re.sub(r'\s+', ' ', input_str.strip())
    
    # 使用正则表达式匹配所有数字（支持整数和浮点数）
    pattern = r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?'
    numbers = re.findall(pattern, input_str)
    
    # 转换为浮点数
    result = []
    for num in numbers:
        try:
            result.append(float(num))
        except ValueError:
            logger.warning(f"无法将 '{num}' 转换为数字，已忽略")
    
    return result

def parse_molecule_names(input_str):
    """解析分子名称列表，支持空格分隔"""
    if not input_str.strip():
        return []
    
    # 将连续多个空格替换为单个空格
    input_str = re.sub(r'\s+', ' ', input_str.strip())
    
    # 按空格分隔并返回列表
    return input_str.split()

def get_output_directory_name():
    """获取用户输入的输出目录名称"""
    while True:
        dir_name = input("请输入计算结果的输出目录名称 [默认: output]: ")
        if not dir_name:
            return "output"  # 默认目录名
        
        # 检查目录名是否合法
        if re.match(r'^[a-zA-Z0-9_\-]+$', dir_name):
            # 检查目录是否已存在
            if os.path.exists(dir_name):
                overwrite = input(f"目录 '{dir_name}' 已存在，是否覆盖? (y/n): ").lower()
                if overwrite == 'y':
                    return dir_name
            else:
                return dir_name
        else:
            print("错误: 目录名只能包含字母、数字、下划线和连字符")

def interactive_parameter_selection(framework_name, cif_dir=None, reuse_params=None):
    """交互式参数选择界面
    
    Args:
        framework_name: 框架名称
        cif_dir: CIF文件目录路径，如果为None则提示用户输入
        reuse_params: 要重用的参数字典，用于批量处理多个框架时避免重复输入
    """
    params = {}
    
    # 如果是重用参数模式
    if reuse_params:
        # 复制可重用的参数
        params['output_dir'] = reuse_params['output_dir']
        params['cif_dir'] = reuse_params['cif_dir']
        params['template'] = reuse_params['template']
        params['molecule_names'] = reuse_params['molecule_names']
        params['param_ranges'] = reuse_params['param_ranges']
        
        # 框架名称不重用，使用当前框架
        params['framework'] = framework_name
        
        # 查找当前框架的CIF文件
        cif_path = find_cif_file(params['framework'], params['cif_dir'])
        if not cif_path:
            logger.error(f"未找到框架 {params['framework']} 对应的CIF文件")
            return None
        params['cif_path'] = cif_path
        
        # 打印重用的参数，供用户参考
        print("\n=== 重用参数 ===")
        print(f"输出目录: {params['output_dir']}")
        print(f"框架: {framework_name}")
        print(f"CIF文件目录: {params['cif_dir']}")
        print(f"模板文件: {params['template']}")
        print(f"分子名称: {params['molecule_names']}")
        
        param_ranges = params['param_ranges']
        print(f"截断半径(Å): {param_ranges['cutoff']}")
        print(f"模拟循环次数: {param_ranges['cycles']}")
        print(f"初始化循环次数: {param_ranges['init_cycles']}")
        print(f"平衡循环次数: {param_ranges['equil_cycles']}")
        print(f"温度(K): {param_ranges['temperature']}")
        print(f"压力(Pa): {param_ranges['pressure']}")
        
        # 计算参数组合数量
        combo_count = (len(param_ranges['cutoff']) * 
                      len(param_ranges['cycles']) * 
                      len(param_ranges['init_cycles']) * 
                      len(param_ranges['equil_cycles']) * 
                      len(param_ranges['temperature']) * 
                      len(param_ranges['pressure']))
        print(f"共将生成 {combo_count} 种参数组合")
        
        return params
    
    # 以下是正常的交互式参数选择流程（非重用模式）
    
    # 获取用户输入的输出目录名称
    print("\n=== 设置输出目录 ===")
    output_dir = get_output_directory_name()
    params['output_dir'] = output_dir
    
    # 框架名称已经提供
    params['framework'] = framework_name
    
    # CIF文件目录（从环境变量或用户输入）
    if not cif_dir:
        cif_dir = os.environ.get('RASPA_CIF_DIR')
        if not cif_dir:
            default_cif_dir = os.path.join(os.getcwd(), "data", "cif")
            cif_dir = input(f"请输入CIF文件目录路径 [默认: {default_cif_dir}]: ")
            cif_dir = cif_dir if cif_dir else default_cif_dir
        else:
            logger.info(f"使用配置文件中的CIF目录: {cif_dir}")
    params['cif_dir'] = cif_dir
    
    # 检查CIF文件是否存在
    cif_path = find_cif_file(params['framework'], params['cif_dir'])
    if not cif_path:
        logger.error(f"未找到框架 {params['framework']} 对应的CIF文件")
        return None
    
    # 模板文件
    default_template = os.path.join(os.getcwd(), "simulation.input")
    template = input(f"请输入模板文件路径 [默认: {default_template}]: ")
    template_path = template if template else default_template
    params['template'] = template_path
    
    # 检查模板文件中的组分数量
    num_components = count_components_in_template(template_path)
    
    # 分子名称
    if num_components > 0:
        print(f"\n检测到模板文件中有 {num_components} 个组分")
        molecule_input = input(f"请输入分子名称（用空格分隔，需要 {num_components} 个）: ")
        molecule_names = parse_molecule_names(molecule_input)
        
        # 检查输入的分子名称数量是否与组分数量匹配
        if len(molecule_names) < num_components:
            print(f"警告: 输入的分子名称数量 ({len(molecule_names)}) 少于模板中的组分数量 ({num_components})")
            print(f"将只替换前 {len(molecule_names)} 个组分的分子名称")
        elif len(molecule_names) > num_components:
            print(f"警告: 输入的分子名称数量 ({len(molecule_names)}) 多于模板中的组分数量 ({num_components})")
            print(f"将只使用前 {num_components} 个分子名称")
            molecule_names = molecule_names[:num_components]
    else:
        # 单个分子名称的情况（传统模式）
        default_molecule = "I2"
        molecule = input(f"请输入分子名称 [默认: {default_molecule}]: ")
        if molecule:
            molecule_names = [molecule]
        else:
            molecule_names = [default_molecule]
    
    params['molecule_names'] = molecule_names
    
    # 参数范围
    print("\n请设置参数筛选范围（多个值用逗号或空格分隔）:")
    
    # 截断半径
    cutoff = input("截断半径(Å) [默认: 12.0]: ")
    cutoff_values = parse_number_list(cutoff) if cutoff else [12.0]
    
    # 模拟循环次数
    cycles = input("模拟循环次数 [默认: 10000]: ")
    cycles_values = [int(x) for x in parse_number_list(cycles)] if cycles else [10000]
    
    # 初始化循环次数
    init_cycles = input("初始化循环次数 [默认: 1000]: ")
    init_cycles_values = [int(x) for x in parse_number_list(init_cycles)] if init_cycles else [1000]
    
    # 平衡循环次数
    equil_cycles = input("平衡循环次数 [默认: 1000]: ")
    equil_cycles_values = [int(x) for x in parse_number_list(equil_cycles)] if equil_cycles else [1000]
    
    # 温度
    temperature = input("温度(K) [默认: 298.0]: ")
    temperature_values = parse_number_list(temperature) if temperature else [298.0]
    
    # 压力
    pressure = input("压力(Pa) [默认: 100000.0]: ")
    pressure_values = parse_number_list(pressure) if pressure else [100000.0]
    
    # 打印解析后的参数值，便于用户确认
    print("\n解析后的参数值:")
    print(f"输出目录: {output_dir}")
    print(f"框架: {framework_name}")
    print(f"CIF文件目录: {cif_dir}")
    print(f"模板文件: {template_path}")
    print(f"分子名称: {molecule_names}")
    print(f"截断半径(Å): {cutoff_values}")
    print(f"模拟循环次数: {cycles_values}")
    print(f"初始化循环次数: {init_cycles_values}")
    print(f"平衡循环次数: {equil_cycles_values}")
    print(f"温度(K): {temperature_values}")
    print(f"压力(Pa): {pressure_values}")
    print(f"共将生成 {len(cutoff_values) * len(cycles_values) * len(init_cycles_values) * len(equil_cycles_values) * len(temperature_values) * len(pressure_values)} 种参数组合")
    
    # 询问用户是否确认
    confirm = input("\n是否确认以上参数? (y/n) [默认: y]: ")
    if confirm.lower() == 'n':
        print("已取消参数设置，请重新运行程序")
        return None
    
    # 参数范围字典
    param_ranges = {
        'cutoff': cutoff_values,
        'cycles': cycles_values,
        'init_cycles': init_cycles_values,
        'equil_cycles': equil_cycles_values,
        'temperature': temperature_values,
        'pressure': pressure_values,
    }
    
    params['param_ranges'] = param_ranges
    params['cif_path'] = cif_path
    
    return params

def process_parameter_combinations(framework, cif_path, param_ranges, template_path, output_dir, job_system, config=None, void_fraction_csv=None):
    """处理所有参数组合并创建作业

    Args:
        framework: 框架名称
        cif_path: CIF文件路径
        param_ranges: 参数范围字典
        template_path: 模板文件路径
        output_dir: 输出目录
        job_system: 作业系统类型
        config: 配置对象
        void_fraction_csv: 空隙率数据字典
    """
    # 生成所有参数组合
    combinations = generate_parameter_combinations(param_ranges)
    logger.info(f"框架 {framework}: 生成了{len(combinations)}种参数组合")

    # 创建输出主目录
    output_base_dir = os.path.join(os.getcwd(), output_dir)
    os.makedirs(output_base_dir, exist_ok=True)

    # 创建框架目录
    framework_dir = os.path.join(output_base_dir, framework)
    os.makedirs(framework_dir, exist_ok=True)

    # 处理每个参数组合
    jobs = []
    for combo in combinations:
        # 生成参数组合目录名
        param_dir_name = generate_directory_name(combo)
        param_dir = os.path.join(framework_dir, param_dir_name)
        os.makedirs(param_dir, exist_ok=True)

        # 准备参数字典
        sim_params = combo.copy()
        sim_params['framework'] = framework

        # 创建simulation.input文件
        sim_input_path = os.path.join(param_dir, "simulation.input")

        if create_simulation_input(template_path, sim_params, cif_path, sim_input_path, config, void_fraction_csv):
            # 创建作业脚本
            job_name = f"{framework}_{param_dir_name}"
            job_script_path = create_job_script(param_dir, job_name, job_system)

            # 提交作业
            job_id = submit_job(job_script_path, job_system)
            if job_id:
                jobs.append({
                    'param_dir': param_dir,
                    'job_id': job_id,
                    'params': combo
                })
                print(f"  ✓ 作业已提交: {job_name} (ID: {job_id})")

    return jobs

def main():
    """主函数 - 纯配置模式"""
    try:
        # 解析命令行参数
        parser = setup_arg_parser()
        args = parser.parse_args()

        # 加载配置文件
        config = load_config()
        if not config:
            logger.error("无法加载配置文件,请检查config.yaml是否存在")
            return 1

        # 如果指定了配置文件,使用指定的配置
        if args.config:
            try:
                with open(args.config, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    logger.info(f"使用指定的配置文件: {args.config}")
            except Exception as e:
                logger.error(f"无法加载配置文件 {args.config}: {e}")
                return 1

        # 从配置文件获取参数
        env_config = config.get('environment', {})
        calc_config = config.get('calculation', {})

        # 检测 RASPA 版本
        raspa_version = env_config.get('raspa_version', 'raspa2').lower()
        print(f"🔧 RASPA 版本: {raspa_version.upper()}")

        # RASPA3 JSON 目录（用于复制 force_field.json 和分子文件）
        json_dir = None
        if raspa_version == 'raspa3':
            json_dir = env_config.get('raspa3_json_dir', '')
            if json_dir:
                print(f"📁 RASPA3 JSON 目录: {json_dir}")

        csv_file = args.csv_file or calc_config.get('csv_file_path')
        framework_col = calc_config.get('framework_column', 'refcode')

        # 根据 RASPA 版本选择 CIF 目录
        if args.cif_dir:
            cif_dir = args.cif_dir
        elif raspa_version == 'raspa3':
            cif_dir = env_config.get('raspa3_cif_base_path', '')
        else:
            cif_dir = env_config.get('raspa2_cif_dir', '') or env_config.get('cif_dir', '')

        # 根据 RASPA 版本选择模板文件
        if args.template:
            template_path = args.template
        elif raspa_version == 'raspa3':
            template_path = env_config.get('raspa3_template_path', '')
        else:
            template_path = calc_config.get('template_path', '') or env_config.get('raspa2_template_path', '')

        # 参数筛选配置
        screening_config = config.get('parameter_screening', {})
        output_dir = screening_config.get('output_directory', 'param_screening_output')
        param_ranges = screening_config.get('parameters', {})

        # 验证必需参数（使用 print 确保错误可见）
        if not csv_file:
            print("❌ 错误: 缺少CSV文件路径")
            print("   请在config.yaml中配置 calculation.csv_file_path 或使用 --csv-file 参数")
            return 1

        if not cif_dir:
            print("❌ 错误: 缺少CIF目录")
            if raspa_version == 'raspa3':
                print("   请在config.yaml中配置 environment.raspa3_cif_base_path")
            else:
                print("   请在config.yaml中配置 environment.raspa2_cif_dir")
            return 1

        if not template_path:
            print("❌ 错误: 缺少模板文件路径")
            if raspa_version == 'raspa3':
                print("   请在config.yaml中配置 environment.raspa3_template_path")
            else:
                print("   请在config.yaml中配置 calculation.template_path")
            return 1

        if not os.path.exists(template_path):
            print(f"❌ 错误: 模板文件不存在: {template_path}")
            return 1

        if not param_ranges:
            logger.warning("未配置参数筛选范围,将使用模板默认值")

        # 从CSV获取框架列号
        column_number = args.column_number
        if not column_number:
            try:
                df = pd.read_csv(csv_file)
                if framework_col in df.columns:
                    column_number = str(df.columns.get_loc(framework_col) + 1)
                    logger.info(f"从配置文件获取框架列: {framework_col} (第{column_number}列)")
                else:
                    logger.error(f"配置的框架列 '{framework_col}' 在CSV文件中不存在")
                    return 1
            except Exception as e:
                logger.error(f"读取CSV文件失败: {e}")
                return 1

        # 检测作业系统类型
        if args.job_system == 'auto':
            job_system = detect_job_system()
        else:
            job_system = args.job_system.lower()

        logger.info(f"检测到作业系统类型: {job_system}")

        # OpenBLAS环境变量设置
        os.environ['OPENBLAS_NUM_THREADS'] = '1'
        os.environ['OMP_NUM_THREADS'] = '1'
        os.environ['MKL_NUM_THREADS'] = '1'

        # 清除可能干扰的Python路径环境变量
        if 'PYTHONPATH' in os.environ:
            del os.environ['PYTHONPATH']

        # 读取CSV文件中的框架名称
        framework_names = read_csv_data(csv_file, column_number)
        if not framework_names:
            logger.error("没有从CSV文件中读取到有效的框架名称")
            return 1

        # 显示配置摘要
        print("\n" + "="*60)
        print("📋 参数筛选配置摘要")
        print("="*60)
        print(f"CSV文件: {csv_file}")
        print(f"框架列: {framework_col} (第{column_number}列)")
        print(f"框架数量: {len(framework_names)}")
        print(f"CIF目录: {cif_dir}")
        print(f"模板文件: {template_path}")
        print(f"输出目录: {output_dir}")
        print(f"作业系统: {job_system}")

        if param_ranges:
            print(f"\n🔧 筛选参数:")
            for param, values in param_ranges.items():
                print(f"  {param}: {values}")

            # 计算组合数
            combo_count = 1
            for values in param_ranges.values():
                combo_count *= len(values)
            print(f"\n📊 每个框架将生成 {combo_count} 种参数组合")
            print(f"📊 总计将提交 {len(framework_names) * combo_count} 个作业")
        else:
            print(f"\n⚠️  未配置筛选参数,将使用模板默认值")

        print("="*60)

        # 交互：仅保留“预览 + 提交确认”，减少不必要的提问
        def ask_yes_no(prompt: str, default_yes=True):
            d = 'y' if default_yes else 'n'
            ans = input(f"{prompt} (y/n) [默认: {d}]: ").strip().lower()
            if not ans:
                return default_yes
            return ans in ('y', 'yes')

        # 预览：展示首个框架 + 首个参数组合的配置文件内容片段
        try:
            import tempfile
            preview_fw = framework_names[0]
            preview_cif = find_cif_file(preview_fw, cif_dir)
            preview_combo = next(iter(generate_parameter_combinations(param_ranges))) if param_ranges else {}
            sim_params = preview_combo.copy(); sim_params['framework'] = preview_fw
            with tempfile.TemporaryDirectory() as td:
                if raspa_version == 'raspa3':
                    # RASPA3: 预览 simulation.json
                    preview_path = os.path.join(td, 'simulation.json')
                    if preview_cif and create_simulation_json(template_path, sim_params, preview_cif, preview_path, config, None):
                        print("\n=== 示例 simulation.json 预览（首个框架 + 首个参数组合）===\n")
                        try:
                            with open(preview_path, 'r', encoding='utf-8') as pf:
                                content = pf.read()
                            print(content)
                        except Exception:
                            pass
                else:
                    # RASPA2: 预览 simulation.input
                    preview_path = os.path.join(td, 'simulation.input')
                    if preview_cif and create_simulation_input(template_path, sim_params, preview_cif, preview_path, config, None):
                        print("\n=== 示例 simulation.input 预览（首个框架 + 首个参数组合）===\n")
                        try:
                            with open(preview_path, 'r', encoding='utf-8') as pf:
                                content = pf.read()
                            # 打印前若干行，避免刷屏
                            lines = content.splitlines()
                            head = lines[:80]
                            print("\n".join(head))
                            if len(lines) > len(head):
                                print("\n... (已截断预览，仅展示前80行) ...\n")
                        except Exception:
                            pass
        except Exception:
            # 预览失败不影响流程
            pass

        # 最终仅保留一次“是否提交作业？”确认
        total_jobs_est = len(framework_names) * (combo_count if param_ranges else 1)
        if not ask_yes_no(f"确认继续提交作业? 预计数量: {total_jobs_est}", default_yes=True):
            print("已取消")
            return 0

        # 加载空隙率数据(如果配置启用)
        void_fraction_csv = None
        use_void_csv = config.get('calculation', {}).get('use_void_csv', False)
        if use_void_csv:
            void_csv_file = config.get('calculation', {}).get('void_csv_file', csv_file)
            void_column = config.get('calculation', {}).get('void_column', 'VF')
            void_fraction_csv = load_void_fraction_from_csv(void_csv_file, framework_col, void_column)
            if void_fraction_csv:
                print(f"\n📊 已从CSV加载 {len(void_fraction_csv)} 个框架的空隙率数据")

        # 处理每个框架
        all_jobs = []
        for i, framework in enumerate(framework_names, 1):
            print(f"\n[{i}/{len(framework_names)}] 处理框架: {framework}")

            # 查找CIF文件
            cif_path = find_cif_file(framework, cif_dir)
            if not cif_path:
                logger.error(f"  ✗ 未找到框架 {framework} 的CIF文件,跳过")
                continue

            logger.info(f"  ✓ CIF文件: {cif_path}")

            # 根据 RASPA 版本选择处理函数
            if raspa_version == 'raspa3':
                # RASPA3: 使用 JSON 格式
                jobs = process_parameter_combinations_raspa3(
                    framework=framework,
                    cif_path=cif_path,
                    param_ranges=param_ranges,
                    template_path=template_path,
                    output_dir=output_dir,
                    job_system=job_system,
                    config=config,
                    void_fraction_csv=void_fraction_csv,
                    json_dir=json_dir
                )
            else:
                # RASPA2: 使用文本格式
                jobs = process_parameter_combinations(
                    framework=framework,
                    cif_path=cif_path,
                    param_ranges=param_ranges,
                    template_path=template_path,
                    output_dir=output_dir,
                    job_system=job_system,
                    config=config,
                    void_fraction_csv=void_fraction_csv
                )
            all_jobs.extend(jobs)

            # 将作业信息写入文件
            jobs_file = os.path.join(os.getcwd(), output_dir, framework, "jobs.json")
            with open(jobs_file, 'w') as f:
                json.dump(jobs, f, indent=2)

            logger.info(f"  ✓ 框架 {framework} 的作业信息已保存到: {jobs_file}")

        # 总结
        print("\n" + "="*60)
        if all_jobs:
            print(f"✅ 成功提交了 {len(all_jobs)} 个作业")
            print(f"📁 结果将保存在: {output_dir}/")
            print("="*60)
            return 0
        else:
            print("❌ 没有成功提交任何作业")
            print("="*60)
            return 1

    except KeyboardInterrupt:
        logger.info("\n用户中断操作")
        return 1
    except Exception as e:
        logger.error(f"程序执行过程中发生错误: {e}")
        logger.debug(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main()) 
