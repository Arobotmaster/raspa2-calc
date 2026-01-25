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
from contextlib import contextmanager
from tqdm import tqdm
try:
    import yaml  # type: ignore
except Exception:
    yaml = None
from raspa_calc.infra.runner.cif import count_numbered_labels, locate_cif_file
from raspa_calc.infra.runner.csv_utils import read_csv_with_fallbacks
from raspa_calc.infra.runner.env import _env_flag, _positive_int
from raspa_calc.infra.runner.inputs import get_cpu_cores_with_plan
from raspa_calc.infra.runner.submit_utils import _parse_submit_index, _should_print_submit_line
from raspa_calc.infra.runner.void_utils import load_void_fraction_from_csv

# 配置读取
from raspa_calc.runtime import config as common_config

# 导入calculate_params模块中的必要函数
from raspa_calc.domain.algorithms.calculate_params import (
    process_structure_file,
    get_cif_cell_parameters,
    load_cache,
    save_cache,
)
from raspa_calc.domain.algorithms.raspa3_io import (
    apply_component_names,
    apply_mser_settings,
    apply_system_settings,
    copy_force_field_and_components,
    finalize_simulation_config,
    write_simulation_json,
)
from raspa_calc.infra.job_scripts import (
    create_job_script,
    create_job_script_raspa3,
    submit_job,
)

def _init_logger() -> logging.Logger:
    logger = logging.getLogger("parameter_screening")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.propagate = False
    return logger


logger = _init_logger()


class _AbortOnWarningFilter(logging.Filter):
    def filter(self, record):
        if record.levelno >= logging.WARNING:
            msg = record.getMessage()
            print(f"❌ 检测到警告，已终止: [{record.name}] {msg}", file=sys.stderr)
            raise SystemExit(1)
        return True

# Backward-compatible alias
find_cif_file = locate_cif_file

@contextmanager
def suppress_info_logs():
    """临时屏蔽 INFO 日志，保留 WARNING/ERROR 以减少噪声。"""
    prev_disable = logging.root.manager.disable
    logging.disable(logging.INFO)
    try:
        yield
    finally:
        logging.disable(prev_disable)

def load_config(config_path=None):
    """加载配置文件"""
    if not common_config.HAS_YAML:
        return None

    config, used_path = common_config.load_config(config_path=config_path)
    if used_path:
        if config_path:
            logger.info(f"使用指定的配置文件: {used_path}")
        else:
            logger.info(f"配置文件已加载: {used_path}")
        return config
    return None

def get_mser_settings(config):
    """合并 pyMSER 配置（parameter_screening 优先，其次 calculation）"""
    if not config:
        return {}

    merged = {}
    calc_mser = config.get('calculation', {}).get('mser', {})
    screening_mser = config.get('parameter_screening', {}).get('mser', {})

    if calc_mser:
        merged.update(calc_mser)
    if screening_mser:
        merged.update(screening_mser)

    return merged

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
            "template": "scripts/shell/templates/schedulers/sbatch.sh",
            "submit_cmd": "sbatch"
        }
    elif job_system == "pbs":
        return {
            "template": "scripts/shell/templates/schedulers/pbs.sh",
            "submit_cmd": "qsub"
        }
    else:
        return {
            "template": "scripts/shell/templates/schedulers/local.sh",
            "submit_cmd": "bash"
        }

def read_csv_data(csv_path, column_number):
    """读取CSV文件中的框架数据"""
    try:
        df = read_csv_with_fallbacks(csv_path)

        # 获取指定列的框架名称
        col_idx = int(column_number) - 1
        if 0 <= col_idx < len(df.columns):
            frameworks = df.iloc[:, col_idx].dropna().unique().tolist()
            logger.info(f"成功从{csv_path}读取数据，共{len(frameworks)}个框架")
            return frameworks
        else:
            logger.error(f"列号{column_number}超出范围，CSV文件只有{len(df.columns)}列")
            return []
    except Exception as e:
        logger.error(f"读取CSV文件失败: {e}")
        return []



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

def copy_raspa3_json_files(json_dir, output_dir, component_names=None, cif_path=None):
    """复制 RASPA3 所需的 JSON 文件到任务目录（自动筛选力场所需原子）

    Args:
        json_dir: RASPA3 JSON 文件目录（包含 force_field.json 和分子定义文件）
        output_dir: 任务输出目录
        component_names: 组件名称列表，用于确定需要复制哪些分子文件
        cif_path: 框架 CIF 路径，用于筛选 force_field.json 中的原子

    Returns:
        bool: 成功返回 True
    """
    try:
        if not os.path.isdir(json_dir):
            logger.warning(f"raspa3_json_dir 不存在: {json_dir}")
            return False

        os.makedirs(output_dir, exist_ok=True)
        copied = set()

        def copy_file(src, dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            copied.add(os.path.relpath(dest, output_dir))

        # 复制 force_field.json 与组件 JSON（按 CIF/气体筛选）
        copy_force_field_and_components(
            json_dir,
            output_dir,
            component_names=component_names,
            cif_path=cif_path,
            log=logger,
        )
        ff_src = os.path.join(json_dir, "force_field.json")
        if os.path.exists(ff_src):
            copied.add("force_field.json")
        if component_names:
            for name in component_names:
                mol_src = os.path.join(json_dir, f"{name}.json")
                if os.path.exists(mol_src):
                    copied.add(f"{name}.json")

        # 复制剩余资源（包含子目录，排除 simulation.json，已复制的 force_field.json）
        for root, _, files in os.walk(json_dir):
            rel_root = os.path.relpath(root, json_dir)
            for f in files:
                rel_path = os.path.join(rel_root, f) if rel_root != '.' else f
                if f == "simulation.json":
                    continue  # 由生成器创建
                if rel_path == "force_field.json":
                    continue  # 已处理过滤版
                if component_names and f.endswith(".json") and os.path.splitext(f)[0] in component_names:
                    continue  # 已复制组件 JSON
                if rel_path in copied:
                    continue

                src = os.path.join(root, f)
                dest = os.path.join(output_dir, rel_path)
                copy_file(src, dest)
                logger.debug(f"复制 {rel_path} 到 {dest}")

        logger.info(f"已复制 RASPA3 JSON 资源 {len(copied)} 个到 {output_dir}")
        return True
    except Exception as e:
        logger.error(f"复制 RASPA3 JSON 文件失败: {e}")
        return False


def create_simulation_json(template_path, params, cif_path, output_path, config=None, void_fraction_csv=None, mser_config=None, result_cache=None):
    """根据模板和参数创建 RASPA3 simulation.json 文件

    Args:
        template_path: JSON 模板文件路径
        params: 参数字典,包含要替换的参数
        cif_path: CIF 文件路径
        output_path: 输出文件路径
        config: 配置对象
        void_fraction_csv: 孔隙率数据字典
        mser_config: pyMSER 配置（可覆盖）
        result_cache: 计算结果缓存字典

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
        mser_settings = mser_config or {}
        mser_enable = bool(mser_settings.get('enable', False))
        mser_add_cycles = int(mser_settings.get('add_cycles', 500)) if mser_enable else None

        # 读取模板文件
        with open(template_path, 'r', encoding='utf-8') as f:
            sim_config = json.load(f)

        # 获取框架名称和 CIF 路径
        framework_name = params.get('framework', '')

        # 设置 Systems[0].Name 为 CIF 绝对路径（RASPA3 需要绝对路径）
        system_cfg = apply_system_settings(sim_config, cif_path=cif_path, use_abs_cif=True)
        if cif_path and os.path.exists(cif_path):
            logger.info(f"设置 CIF 路径: {system_cfg['Name']}")
        else:
            logger.warning("未找到有效的 CIF 路径，保留模板中的 Name 字段")

        # 计算 UnitCells（如果启用）
        auto_unit_cells = config.get('parameter_screening', {}).get('auto_unit_cells', True) if config else True
        cutoff_value = float(params.get('CutOff') or params.get('CutOffVDW') or params.get('cutoff', 12.0))

        if auto_unit_cells and cif_path and os.path.exists(cif_path):
            try:
                success, unit_cells_tuple, void_fraction = process_structure_file(
                    cif_path, cutoff_value, result_cache=result_cache
                )
                if success and unit_cells_tuple:
                    apply_system_settings(sim_config, unit_cells=unit_cells_tuple)
                    logger.info(f"计算 NumberOfUnitCells: {unit_cells_tuple}")

                    # 设置孔隙率
                    if void_fraction is not None:
                        apply_system_settings(sim_config, void_fraction=void_fraction)
                        logger.info(f"设置 HeliumVoidFraction: {void_fraction}")
            except Exception as e:
                logger.warning(f"计算 UnitCells 失败: {e}")

        # 从 CSV 获取孔隙率（如果配置了）
        if void_fraction_csv and framework_name:
            vf = void_fraction_csv.get(framework_name)
            if vf is not None:
                apply_system_settings(sim_config, void_fraction=vf)
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
                system_cfg[json_key] = params[param_key]
                logger.debug(f"设置 Systems[0].{json_key}: {params[param_key]}")

        # 覆盖 Components 中的分子名称（若参数提供 Name）
        component_override = params.get('Name') or params.get('name')
        component_names_override = None
        if component_override is not None:
            if isinstance(component_override, (list, tuple)):
                component_names_override = list(component_override)
            elif isinstance(component_override, str):
                component_names_override = parse_molecule_names(component_override)

        if component_names_override:
            apply_component_names(sim_config, component_names_override, log=logger)

        # pyMSER 续跑需要重启文件；若启用则补足配置并按追加步数启动（与高通量模式一致）
        if mser_enable:
            apply_mser_settings(sim_config, mser_enable=mser_enable, add_cycles=mser_add_cycles)

        # 统一移除二进制重启相关字段，使用 JSON RestartFileName 续跑
        finalize_simulation_config(sim_config)

        # 写入输出文件
        write_simulation_json(sim_config, output_path, ensure_ascii=False)

        logger.info(f"成功创建 RASPA3 配置文件: {output_path}")
        return True

    except Exception as e:
        logger.error(f"创建 simulation.json 文件失败: {e}")
        logger.debug(traceback.format_exc())
        return False


def process_parameter_combinations_raspa3(framework, cif_path, param_ranges, template_path,
                                          output_dir, job_system, config=None,
                                          void_fraction_csv=None, json_dir=None, mser_config=None,
                                          result_cache=None, progress=None):
    """处理 RASPA3 所有参数组合并创建作业

    Args:
        framework: 框架名称
        cif_path: CIF 文件路径
        param_ranges: 参数范围字典
        template_path: JSON 模板文件路径
        output_dir: 输出目录
        job_system: 作业系统类型
        config: 配置对象
        void_fraction_csv: 孔隙率数据字典
        json_dir: RASPA3 JSON 文件目录
        mser_config: pyMSER 配置
        result_cache: 计算结果缓存字典
        progress: 可选的进度回调
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

    # 获取模板中的组件名称（用于复制分子文件的默认值）
    template_component_names = None
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            template_data = json.load(f)
            components = template_data.get('Components', [])
            template_component_names = list(set(c.get('Name', '') for c in components if c.get('Name')))
    except Exception:
        pass

    # 处理每个参数组合
    tasks = []
    for combo in combinations:
        # 生成参数组合目录名
        param_dir_name = generate_directory_name(combo)
        param_dir = os.path.join(framework_dir, param_dir_name)
        os.makedirs(param_dir, exist_ok=True)
        try:
            with open(os.path.join(param_dir, "status.txt"), 'w') as sf:
                sf.write("pending")
            base_dir = os.path.basename(param_dir)
            parent_dir = os.path.dirname(param_dir)
        except Exception:
            pass

        # 组件名称覆盖：优先组合中的 Name，其次模板中的组件
        component_names = template_component_names
        if 'Name' in combo:
            val = combo['Name']
            if isinstance(val, (list, tuple)):
                component_names = list(val)
            elif isinstance(val, str):
                component_names = parse_molecule_names(val)

        # 复制 RASPA3 JSON 文件（按框架/组分筛选力场）
        if json_dir:
            copy_raspa3_json_files(json_dir, param_dir, component_names, cif_path)

        # 准备参数字典
        sim_params = combo.copy()
        sim_params['framework'] = framework

        # 创建 simulation.json 文件
        sim_json_path = os.path.join(param_dir, "simulation.json")

        try:
            if create_simulation_json(
                template_path,
                sim_params,
                cif_path,
                sim_json_path,
                config,
                void_fraction_csv,
                mser_config,
                result_cache=result_cache,
            ):
                tasks.append(param_dir)
        finally:
            if progress:
                progress()

    return tasks

# ============================================================
#                    RASPA2 参数筛选 (原有功能)
# ============================================================

def create_simulation_input(template_path, params, cif_path, output_path, config=None, void_fraction_csv=None, mser_config=None, result_cache=None):
    """根据模板和参数创建simulation.input文件 - 支持通用参数替换

    Args:
        template_path: 模板文件路径
        params: 参数字典,包含要替换的参数
        cif_path: CIF文件路径
        output_path: 输出文件路径
        config: 配置对象,用于获取auto_unit_cells等设置
        void_fraction_csv: 孔隙率数据字典(从CSV读取)
        mser_config: pyMSER 配置
        result_cache: 计算结果缓存字典
    """
    try:
        # 读取模板文件
        with open(template_path, 'r') as f:
            template = f.read()

        # 分行处理模板文件
        lines = template.split('\n')

        # pyMSER 配置
        mser_settings = mser_config or {}
        mser_enable = bool(mser_settings.get('enable', False))
        mser_add_cycles = int(mser_settings.get('add_cycles', 500)) if mser_enable else 500
        mser_target_cycles = int(mser_settings.get('target_cycles', 1000)) if mser_enable else None
        restart_set = False
        write_restart_set = False
        number_cycles_set = False
        init_cycles_set = False
        equil_cycles_set = False
        print_every_set = False

        # 从CIF文件计算UnitCells参数
        unit_cells = None
        void_fraction = None
        auto_unit_cells = config.get('parameter_screening', {}).get('auto_unit_cells', True) if config else True

        # 检查是否从CSV获取孔隙率
        use_void_csv = config.get('calculation', {}).get('use_void_csv', False) if config else False
        framework_name = params.get('framework')

        if use_void_csv and void_fraction_csv and framework_name:
            # 从CSV字典获取孔隙率
            void_fraction = void_fraction_csv.get(framework_name)
            if void_fraction is not None:
                logger.info(f"从CSV文件获取孔隙率: {void_fraction}")
            else:
                logger.warning(f"CSV中未找到框架 {framework_name} 的孔隙率数据")

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
                    framework_column=framework_column,
                    result_cache=result_cache
                )

                if success and unit_cells_tuple:
                    unit_cells = unit_cells_tuple
                    # 如果process_structure_file从CSV读取了孔隙率,使用它
                    # 否则使用之前从void_fraction_csv字典获取的值
                    if void_fraction is None and void_fraction_value is not None:
                        void_fraction = void_fraction_value
                        logger.info(f"从CSV/CIF文件获取到孔隙率: {void_fraction}")
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
            lower_line = line.strip().lower()

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
                elif mser_enable:
                    # 覆盖模板中的循环与打印设置以适配 pyMSER
                    if lower_line.startswith('numberofcycles'):
                        number_cycles_set = True
                        lines[i] = f"{indent}NumberOfCycles{spaces}{mser_add_cycles}"
                        logger.info(f"为 pyMSER 覆盖 NumberOfCycles -> {mser_add_cycles}")
                    elif lower_line.startswith('numberofinitializationcycles'):
                        init_cycles_set = True
                        lines[i] = f"{indent}NumberOfInitializationCycles{spaces}0"
                    elif lower_line.startswith('numberofequilibrationcycles'):
                        equil_cycles_set = True
                        lines[i] = f"{indent}NumberOfEquilibrationCycles{spaces}0"
                    elif lower_line.startswith('printevery'):
                        print_every_set = True
                        lines[i] = f"{indent}PrintEvery{spaces}1"

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

            # pyMSER: 确保写重启与 RestartFile 设置
            if mser_enable and lower_line.startswith('writebinaryrestartevery'):
                write_restart_set = True
                pattern = r'(\s*WriteBinaryRestartEvery\s+)(\S+)'
                match = re.match(pattern, line, re.IGNORECASE)
                if match:
                    prefix = match.group(1)
                    try:
                        val = int(match.group(2))
                    except Exception:
                        val = 0
                    if val <= 0:
                        lines[i] = f"{prefix}{max(1, mser_add_cycles)}"
                        logger.info(f"为 pyMSER 更新 WriteBinaryRestartEvery: {max(1, mser_add_cycles)}")

            if mser_enable and lower_line.startswith('restartfile'):
                restart_set = True
                pattern = r'(\s*RestartFile\s+)(\S+)'
                match = re.match(pattern, line, re.IGNORECASE)
                if match:
                    prefix = match.group(1)
                    lines[i] = f"{prefix}no"
                    logger.info("为 pyMSER 设置 RestartFile no")

        # 若模板缺少重启配置，且启用了 pyMSER，则追加
        if mser_enable:
            if not write_restart_set:
                lines.append(f"WriteBinaryRestartEvery {max(1, mser_add_cycles)}")
                logger.info(f"添加 WriteBinaryRestartEvery {max(1, mser_add_cycles)} 以支持 pyMSER")
            if not restart_set:
                lines.append("RestartFile no")
            if not number_cycles_set:
                lines.append(f"NumberOfCycles {mser_add_cycles}")
            if not init_cycles_set:
                lines.append("NumberOfInitializationCycles 0")
            if not equil_cycles_set:
                lines.append("NumberOfEquilibrationCycles 0")
            if not print_every_set:
                lines.append("PrintEvery 1")
            if mser_target_cycles is not None:
                lines.append(f"# MSER target_cycles = {mser_target_cycles}")

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
        cif_path = locate_cif_file(params['framework'], params['cif_dir'])
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
    cif_path = locate_cif_file(params['framework'], params['cif_dir'])
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

def process_parameter_combinations(framework, cif_path, param_ranges, template_path, output_dir,
                                   job_system, config=None, void_fraction_csv=None,
                                   mser_config=None, result_cache=None, progress=None):
    """处理所有参数组合并创建作业

    Args:
        framework: 框架名称
        cif_path: CIF文件路径
        param_ranges: 参数范围字典
        template_path: 模板文件路径
        output_dir: 输出目录
        job_system: 作业系统类型
        config: 配置对象
        void_fraction_csv: 孔隙率数据字典
        mser_config: pyMSER 配置
        result_cache: 计算结果缓存字典
        progress: 可选的进度回调
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
    tasks = []
    for combo in combinations:
        # 生成参数组合目录名
        param_dir_name = generate_directory_name(combo)
        param_dir = os.path.join(framework_dir, param_dir_name)
        os.makedirs(param_dir, exist_ok=True)
        try:
            with open(os.path.join(param_dir, "status.txt"), 'w') as sf:
                sf.write("pending")
            base_dir = os.path.basename(param_dir)
            parent_dir = os.path.dirname(param_dir)
        except Exception:
            pass

        # 准备参数字典
        sim_params = combo.copy()
        sim_params['framework'] = framework

        # 创建simulation.input文件
        sim_input_path = os.path.join(param_dir, "simulation.input")

        try:
            if create_simulation_input(
                template_path,
                sim_params,
                cif_path,
                sim_input_path,
                config,
                void_fraction_csv,
                mser_config,
                result_cache=result_cache,
            ):
                tasks.append(param_dir)
        finally:
            if progress:
                progress()

    return tasks

def main():
    """主函数 - 纯配置模式"""
    try:
        logger.addFilter(_AbortOnWarningFilter())
        logging.getLogger().addFilter(_AbortOnWarningFilter())

        # 解析命令行参数
        parser = setup_arg_parser()
        args = parser.parse_args()

        # 加载配置文件
        config = load_config(args.config)
        if not config:
            if args.config:
                logger.error(f"无法加载配置文件 {args.config}: 请检查路径")
            else:
                logger.error("无法加载配置文件,请检查config.yaml是否存在")
            return 1

        # 从配置文件获取参数
        env_config = config.get('environment', {})
        calc_config = config.get('calculation', {})
        mser_config = get_mser_settings(config)

        # 检测 RASPA 版本
        raspa_version = env_config.get('raspa_version', 'raspa2').lower()
        print(f"\n步骤1：初始化设置 (RASPA版本: {raspa_version.upper()})")

        # RASPA3 JSON 目录（用于复制 force_field.json 和分子文件）
        json_dir = None
        if raspa_version == 'raspa3':
            json_dir = env_config.get('raspa3_json_dir', '')
            if json_dir:
                print(f"📁 RASPA3 JSON 目录: {json_dir}")

        csv_file = args.csv_file or calc_config.get('csv_file_path')
        framework_col = calc_config.get('framework_column', 'refcode')

        # 根据 RASPA 版本选择 CIF 目录
        cif_dir = ""
        cif_dir_source = None
        if args.cif_dir:
            cif_dir = args.cif_dir
            cif_dir_source = "args"
        elif raspa_version == 'raspa3':
            cif_dir = env_config.get('raspa3_cif_base_path', '')
            cif_dir_source = "config" if cif_dir else None
        else:
            cif_dir = env_config.get('raspa2_cif_dir', '')
            cif_dir_source = "config" if cif_dir else None

        # 根据 RASPA 版本选择模板文件
        if args.template:
            template_path = args.template
        elif raspa_version == 'raspa3':
            template_path = env_config.get('raspa3_template_path', '')
        else:
            template_path = env_config.get('template_path', '')

        # 参数筛选配置
        screening_config = config.get('parameter_screening', {})
        output_dir = screening_config.get('output_directory', 'param_screening_output')
        param_ranges = screening_config.get('parameters', {})

        # CIF 缓存设置
        use_cif_cache = config.get('use_cif_cache', False)
        cif_cache_path = config.get('cif_cache_path') or os.path.join(os.getcwd(), "params_cache.json")
        result_cache = None
        
        if use_cif_cache:
            result_cache = load_cache(cif_cache_path)
            if result_cache:
                logger.info(f"启用 CIF 参数缓存 (已加载 {len(result_cache)} 条记录) | 路径: {cif_cache_path}")
            else:
                logger.info(f"启用 CIF 参数缓存 (无现有缓存) | 路径: {cif_cache_path}")

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
                print("   请在config.yaml中配置 environment.template_path")
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
                df = read_csv_with_fallbacks(csv_file)
                if framework_col in df.columns:
                    column_number = str(df.columns.get_loc(framework_col) + 1)
                    logger.info("使用配置文件中的框架列")
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

        print("\n步骤2：处理CSV文件")
        # 读取CSV文件中的框架名称
        framework_names = read_csv_data(csv_file, column_number)
        if not framework_names:
            logger.error("没有从CSV文件中读取到有效的框架名称")
            return 1
        framework_names = [name for name in framework_names if str(name).strip()]
        if not framework_names:
            logger.error("CSV中没有有效框架名称")
            return 1
        logger.info(f"找到 {len(framework_names)} 个有效框架结构")

        print("\n步骤3：检查CIF文件")
        if cif_dir_source == "args":
            logger.info(f"使用命令行指定CIF目录: {cif_dir}")
        elif cif_dir_source == "config":
            if raspa_version == 'raspa3':
                logger.info(f"使用配置文件中的CIF基础路径 (RASPA3): {cif_dir}")
            else:
                logger.info(f"使用配置文件中的CIF目录: {cif_dir}")

        if not os.path.isdir(cif_dir):
            print(f"⚠️  CIF目录不存在: {cif_dir}")
            create_dir = input("是否创建该目录? (y/n): ").strip().lower()
            if create_dir == "y":
                try:
                    os.makedirs(cif_dir, exist_ok=True)
                    logger.info(f"已创建目录: {cif_dir}")
                except Exception as e:
                    logger.error(f"创建目录失败: {e}")

        logger.info(f"将使用CIF目录: {cif_dir}")
        logger.info("检查框架对应的CIF文件...")
        framework_cif_paths = {}
        missing_cifs = []
        for framework in framework_names:
            cif_path = locate_cif_file(framework, cif_dir)
            if cif_path:
                framework_cif_paths[framework] = cif_path
            else:
                missing_cifs.append(framework)

        if missing_cifs:
            logger.warning(f"以下 {len(missing_cifs)} 个框架缺少CIF文件，将自动跳过：")
            for i, missing in enumerate(missing_cifs[:10], 1):
                logger.warning(f"  {i}. {missing}")
            if len(missing_cifs) > 10:
                logger.warning(f"  ... 及其他 {len(missing_cifs) - 10} 个")
            logger.warning("上述框架将被自动跳过，程序继续处理其余结构。")

        framework_names = list(framework_cif_paths.keys())
        if not framework_names:
            logger.error("所有框架均缺少CIF文件，无法继续计算。")
            return 1
        logger.info(f"共找到 {len(framework_names)} 个框架对应的CIF文件")

        if raspa_version == 'raspa3':
            label_issues = []
            total_label_issues = 0
            check_tasks = []
            logger.info("正在检查 CIF 文件标签格式...")

            for framework in framework_names:
                cif_path = framework_cif_paths.get(framework)
                if not cif_path:
                    continue
                if "cleaned_cif" in os.path.normpath(cif_path).split(os.sep):
                    continue
                check_tasks.append((framework, cif_path))

            if check_tasks:
                for framework, cif_path in check_tasks:
                    issue_count = count_numbered_labels(cif_path)
                    if issue_count > 0:
                        label_issues.append((framework, cif_path, issue_count))
                        total_label_issues += issue_count

            if label_issues:
                preview_limit = 10
                print(
                    f"⚠️  检测到 {len(label_issues)} 个 CIF 文件的 _atom_site_label 含编号，共 {total_label_issues} 条标签存在编号。"
                )
                for fw, path, cnt in label_issues[:preview_limit]:
                    print(f"  - {fw}: {cnt} 个编号标签 ({path})")
                if len(label_issues) > preview_limit:
                    print(f"  ... 仅展示前 {preview_limit} 个框架，另有 {len(label_issues) - preview_limit} 个未列出")

                auto_clean = config.get('parameter_screening', {}).get('auto_clean_cif_labels', False)
                if auto_clean:
                    logger.info("已启用 CIF 标签自动清理 (parameter_screening.auto_clean_cif_labels=true)")
                else:
                    user_choice = input("是否使用 clean_cif_labels.py 自动去除编号? (y/n): ").strip().lower()
                    if user_choice != "y":
                        logger.error("用户拒绝自动清理 CIF 标签，程序终止。请先处理标签后重新运行。")
                        return 1

                target_files = [os.path.basename(path) for _, path, _ in label_issues]
                module_path = "raspa_calc.domain.utils.clean_cif_labels"
                logger.info(
                    "运行标签清理脚本（就地处理有编号的文件）: "
                    f"python -m {module_path} {cif_dir} --in-place --files {', '.join(target_files)}"
                )
                cmd = [sys.executable, "-m", module_path, cif_dir, "--in-place", "--files", *target_files]
                result = subprocess.run(cmd)
                if result.returncode != 0:
                    logger.error("标签清理脚本执行失败，程序终止。")
                    return 1

                missing_cleaned = [f for f in target_files if not os.path.exists(os.path.join(cif_dir, f))]
                if missing_cleaned:
                    logger.error(f"以下文件未成功完成就地清理: {', '.join(missing_cleaned)}")
                    return 1

                logger.info(f"已完成 {len(target_files)} 个 CIF 的就地清理。")

        # 计算组合数
        combo_count = 1
        if param_ranges:
            for values in param_ranges.values():
                combo_count *= len(values)
        total_jobs_est = len(framework_names) * combo_count

        output_base_dir = os.path.join(os.getcwd(), output_dir)
        os.makedirs(output_base_dir, exist_ok=True)

        print("\n步骤4：集群资源与并发设置")
        plan_path = os.path.join(output_base_dir, ".raspa_node_plan")
        cpu_cores = get_cpu_cores_with_plan(total_jobs_est, plan_path=plan_path)
        if cpu_cores <= 0:
            print("❌ 无有效CPU核心数，任务未提交")
            return 1

        # 加载孔隙率数据(如果配置启用)
        void_fraction_csv = None
        use_void_csv = config.get('calculation', {}).get('use_void_csv', False)
        void_csv_file = None
        void_column = None
        if use_void_csv:
            void_csv_file = config.get('calculation', {}).get('void_csv_file', csv_file)
            void_column = config.get('calculation', {}).get('void_column', 'VF')
            void_fraction_csv = load_void_fraction_from_csv(void_csv_file, framework_col, void_column)

        print("\n步骤5：simulation文件预览与任务简介")
        print("\n" + "="*60)
        print("📋 参数筛选任务简介")
        print("="*60)
        print(f"CSV文件: {csv_file}")
        print(f"有效框架数量: {len(framework_names)}")
        print(f"CIF目录: {cif_dir}")
        print(f"模板文件: {template_path}")
        print(f"输出目录: {output_dir}")
        print(f"CPU核心数: {cpu_cores}")
        print(f"作业系统: {job_system}")
        print("提交方式: 高通量调度")

        if param_ranges:
            print(f"\n🔧 筛选参数:")
            for param, values in param_ranges.items():
                print(f"  {param}: {values}")
            print(f"\n📊 每个框架将生成 {combo_count} 种参数组合")
            print(f"📊 总计将提交 {total_jobs_est} 个作业")
        else:
            print(f"\n⚠️  未配置筛选参数,将使用模板默认值")

        if use_void_csv:
            print(f"\n📊 孔隙率CSV: {void_csv_file}")
            if void_fraction_csv:
                print(f"📊 已从CSV加载 {len(void_fraction_csv)} 个框架的孔隙率数据")

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
            preview_cif = framework_cif_paths.get(preview_fw)
            preview_combo = next(iter(generate_parameter_combinations(param_ranges))) if param_ranges else {}
            sim_params = preview_combo.copy(); sim_params['framework'] = preview_fw
            with tempfile.TemporaryDirectory() as td:
                with suppress_info_logs():
                    if raspa_version == 'raspa3':
                        # RASPA3: 预览 simulation.json
                        preview_path = os.path.join(td, 'simulation.json')
                        if preview_cif and create_simulation_json(template_path, sim_params, preview_cif, preview_path, config, None, mser_config):
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
                        if preview_cif and create_simulation_input(template_path, sim_params, preview_cif, preview_path, config, None, mser_config):
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
        if not ask_yes_no(f"确认继续提交作业? 预计数量: {total_jobs_est}", default_yes=True):
            print("已取消")
            return 0

        print("\n步骤6：生成VF和UnitCells")
        all_tasks = []
        pbar = tqdm(total=total_jobs_est, desc="生成进度", unit="任务")

        def progress_update():
            pbar.update(1)

        try:
            with suppress_info_logs():
                for framework in framework_names:
                    cif_path = framework_cif_paths.get(framework)
                    if not cif_path:
                        continue

                    # 根据 RASPA 版本选择处理函数
                    if raspa_version == 'raspa3':
                        # RASPA3: 使用 JSON 格式
                        task_dirs = process_parameter_combinations_raspa3(
                            framework=framework,
                            cif_path=cif_path,
                            param_ranges=param_ranges,
                            template_path=template_path,
                            output_dir=output_dir,
                            job_system=job_system,
                            config=config,
                            void_fraction_csv=void_fraction_csv,
                            json_dir=json_dir,
                            mser_config=mser_config,
                            result_cache=result_cache,
                            progress=progress_update,
                        )
                    else:
                        # RASPA2: 使用文本格式
                        task_dirs = process_parameter_combinations(
                            framework=framework,
                            cif_path=cif_path,
                            param_ranges=param_ranges,
                            template_path=template_path,
                            output_dir=output_dir,
                            job_system=job_system,
                            config=config,
                            void_fraction_csv=void_fraction_csv,
                            mser_config=mser_config,
                            result_cache=result_cache,
                            progress=progress_update,
                        )
                    all_tasks.extend(task_dirs)
        finally:
            pbar.close()

        # 保存缓存
        if use_cif_cache and result_cache is not None:
            save_cache(result_cache, cif_cache_path)

        # 总结 & 高通量提交
        print("\n" + "="*60)
        if not all_tasks:
            print("❌ 没有成功生成任何任务")
            print("="*60)
            return 1

        output_base_dir = os.path.join(os.getcwd(), output_dir)
        queue_dir = os.path.join(output_base_dir, ".raspa_queue")
        if os.path.isdir(queue_dir):
            shutil.rmtree(queue_dir)
        os.makedirs(queue_dir, exist_ok=True)
        tasks_list_path = os.path.join(queue_dir, "tasks.list")
        with open(tasks_list_path, "w", encoding="utf-8") as f:
            for task_dir in all_tasks:
                rel_path = os.path.relpath(task_dir, output_base_dir)
                f.write(rel_path + "\n")

        # 保存配置快照
        try:
            snap_path = os.path.join(output_base_dir, ".raspa_config.yaml")
            if common_config.HAS_YAML and yaml is not None:
                with open(snap_path, "w", encoding="utf-8") as fh:
                    yaml.safe_dump(config or {}, fh, allow_unicode=True)
            else:
                with open(snap_path, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(config or {}, ensure_ascii=False, indent=2))
            logger.info(f"配置快照已保存: {snap_path}")
        except Exception as e:
            logger.warning(f"保存配置快照失败: {e}")

        actual_cores = min(cpu_cores, len(all_tasks))
        if actual_cores <= 0:
            print("❌ 无有效CPU核心数，任务未提交")
            return 1

        print(f"✅ 已生成 {len(all_tasks)} 个任务")
        print(f"📁 结果目录: {output_dir}/")
        if actual_cores < cpu_cores:
            print(f"提示: 实际任务数少于CPU设置，提交 worker 数量调整为 {actual_cores}")
        print("🚀 提交方式: 高通量调度")
        print("="*60)

        print("\n步骤7：提交任务")
        try:
            tool_dir = os.path.expanduser("~/raspa2-calc/.raspa_tools")
            tasksrun_script = os.path.join(tool_dir, "scripts", "shell", "entrypoints", "submit.sh")

            if not os.path.exists(tasksrun_script):
                logger.error(f"找不到任务提交脚本: {tasksrun_script}")
                logger.info(f"请手动运行以下命令提交任务: bash {tasksrun_script} {actual_cores}")
                return 1

            env = os.environ.copy()
            env["RASPA_WORK_DIR"] = os.getcwd()
            env["RASPA_OUTPUT_DIR"] = output_dir
            env["RASPA_SUBDIR"] = output_dir
            env["RASPA_VERSION"] = raspa_version

            raspa_dir = env_config.get("raspa_dir")
            if raspa_dir and "RASPA_DIR" not in env:
                env["RASPA_DIR"] = raspa_dir

            print(f"将提交 {actual_cores} 个并行作业")
            with subprocess.Popen(
                [tasksrun_script, str(actual_cores)],
                cwd=os.getcwd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            ) as proc:
                submit_verbose = _env_flag("RASPA_SUBMIT_VERBOSE", False)
                submit_every = _positive_int(os.environ.get("RASPA_SUBMIT_LOG_EVERY"), 10)
                submit_every = min(submit_every, max(1, actual_cores))
                if not submit_verbose and submit_every > 1:
                    print(f"提交中... 每 {submit_every} 个任务提示一次 (完整输出可设 RASPA_SUBMIT_VERBOSE=1)")

                submitted = 0
                for line in proc.stdout:
                    line_strip = line.strip()
                    if not line_strip:
                        continue
                    if submit_verbose:
                        print(line_strip)
                        continue

                    idx = _parse_submit_index(line_strip)
                    if idx is not None:
                        submitted = max(submitted, idx)
                        if submitted == 1 or submitted == actual_cores or submitted % submit_every == 0:
                            print(f"正在提交第{submitted}个任务…")
                        continue

                    if _should_print_submit_line(line_strip):
                        print(line_strip)
                ret = proc.wait()

            if ret == 0:
                logger.info(f"✅ 任务提交完成，共提交 {actual_cores} 个任务")
                print(f"总计提交 {actual_cores} 个任务")
                return 0

            logger.error("任务提交失败")
            logger.info(f"请手动运行以下命令提交任务: bash {tasksrun_script} {actual_cores}")
            return 1

        except Exception as e:
            logger.error(f"提交任务时出错: {e}")
            logger.info(f"请手动运行以下命令提交任务: bash {tasksrun_script} {actual_cores}")
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
