#!/usr/bin/env python3
"""
RASPA3 高通量计算输入文件生成器

功能:
- 从 CSV 文件读取框架名列表
- 为每个框架创建任务目录 (mc1, mc2, ...)
- 生成 simulation.json
- 复制 force_field.json 和分子定义文件
- 自动计算 NumberOfUnitCells

用法:
    python -m raspa_calc.algorithms.raspa3_generator --config config.yaml
    或
    python -m raspa_calc.algorithms.raspa3_generator --csv data.csv --framework-column coreid --output-dir output
"""

import os
import sys
import json
import logging
import argparse
import traceback
import pandas as pd

from common import config as common_config

# 复用 calculate_params 模块的功能
from .calculate_params import (
    calculate_perpendicular_widths,
    calculate_UnitCells,
    get_cif_cell_parameters
)
from .raspa3_io import copy_force_field_and_components
from ..task_runner.cif import locate_cif_file

# 配置日志
def setup_logging(log_file="raspa3_generator.log"):
    """设置日志系统"""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

    root_logger.setLevel(logging.DEBUG)

    file_fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_fmt = logging.Formatter('%(levelname)s - %(message)s')

    # 文件处理器
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    return root_logger

logger = setup_logging()


def load_config(config_path):
    """加载配置文件"""
    try:
        return common_config.load_config_file(config_path)
    except FileNotFoundError:
        raise FileNotFoundError(f"配置文件不存在: {config_path}")


def get_frameworks_from_csv(csv_path, framework_column):
    """从 CSV 文件读取框架名列表"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV 文件不存在: {csv_path}")

    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding='utf-8')

    if framework_column not in df.columns:
        raise ValueError(f"CSV 文件中不存在列: {framework_column}")

    frameworks = df[framework_column].dropna().tolist()
    frameworks = [str(f).strip() for f in frameworks if str(f).strip()]

    logger.info(f"从 CSV 文件读取到 {len(frameworks)} 个框架")
    return frameworks


def load_simulation_template(template_path):
    """加载 simulation.json 模板"""
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"模板文件不存在: {template_path}")

    with open(template_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def find_cif_file(framework_name, cif_base_path):
    """查找 CIF 文件"""
    return locate_cif_file(framework_name, cif_base_path)


def calculate_unit_cells_for_cif(cif_path, cutoff=12.0):
    """计算 CIF 文件的 NumberOfUnitCells"""
    try:
        # 使用现有的 calculate_params 函数
        unit_cells = get_cif_cell_parameters(cif_path, cutoff)
        if unit_cells:
            return unit_cells
    except Exception as e:
        logger.warning(f"使用高精度算法计算失败: {e}")

    # 后备方案：直接读取 CIF 参数并简单计算
    try:
        cell_params = {}
        with open(cif_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line.startswith('_cell_length_a'):
                    cell_params['a'] = float(line.split()[1].split('(')[0])
                elif line.startswith('_cell_length_b'):
                    cell_params['b'] = float(line.split()[1].split('(')[0])
                elif line.startswith('_cell_length_c'):
                    cell_params['c'] = float(line.split()[1].split('(')[0])

        if 'a' in cell_params and 'b' in cell_params and 'c' in cell_params:
            import math
            unit_a = max(1, math.ceil(2 * cutoff / cell_params['a']))
            unit_b = max(1, math.ceil(2 * cutoff / cell_params['b']))
            unit_c = max(1, math.ceil(2 * cutoff / cell_params['c']))
            return [unit_a, unit_b, unit_c]
    except Exception as e:
        logger.error(f"后备算法计算失败: {e}")

    return [1, 1, 1]  # 默认值


def copy_json_files_to_task_dir(task_dir, json_dir, components, cif_path=None):
    """复制 JSON 文件到任务目录"""
    component_names = []
    for component in components or []:
        if isinstance(component, dict):
            name = component.get("Name", "")
            if name:
                component_names.append(name)
    copy_force_field_and_components(
        json_dir,
        task_dir,
        component_names=component_names,
        cif_path=cif_path,
        log=logger,
    )


def generate_raspa3_tasks(
    frameworks,
    output_dir,
    template_path,
    json_dir,
    cif_base_path,
    cutoff=12.0,
    void_fraction=0.5
):
    """
    为每个框架生成 RASPA3 任务

    Args:
        frameworks: 框架名列表
        output_dir: 输出目录
        template_path: simulation.json 模板路径
        json_dir: JSON 文件目录 (force_field.json, 分子文件)
        cif_base_path: CIF 文件基础路径
        cutoff: 截断半径
        void_fraction: 默认孔隙率

    Returns:
        (成功数, 失败数)
    """
    # 加载模板
    template = load_simulation_template(template_path)

    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)

    success_count = 0
    fail_count = 0

    try:
        from tqdm import tqdm
        iterator = tqdm(enumerate(frameworks, 1), total=len(frameworks), desc="生成任务", unit="个")
    except ImportError:
        iterator = enumerate(frameworks, 1)
        logger.info(f"开始生成 {len(frameworks)} 个任务...")

    for idx, framework_name in iterator:
        try:
            # 创建任务目录
            task_dir = os.path.join(output_dir, f"mc{idx}")
            os.makedirs(task_dir, exist_ok=True)

            # 查找 CIF 文件
            cif_path = find_cif_file(framework_name, cif_base_path)
            if cif_path is None:
                logger.error(f"找不到框架 {framework_name} 的 CIF 文件")
                fail_count += 1
                continue

            # 计算 NumberOfUnitCells
            unit_cells = calculate_unit_cells_for_cif(cif_path, cutoff)

            # 深拷贝模板
            import copy
            sim_config = copy.deepcopy(template)

            # 更新配置
            if "Systems" in sim_config and len(sim_config["Systems"]) > 0:
                # 设置 CIF 文件绝对路径
                sim_config["Systems"][0]["Name"] = cif_path
                # 设置 NumberOfUnitCells
                sim_config["Systems"][0]["NumberOfUnitCells"] = unit_cells
                # 设置孔隙率
                if "HeliumVoidFraction" in sim_config["Systems"][0]:
                    sim_config["Systems"][0]["HeliumVoidFraction"] = void_fraction

            # 保存 simulation.json
            sim_path = os.path.join(task_dir, "simulation.json")
            with open(sim_path, 'w', encoding='utf-8') as f:
                json.dump(sim_config, f, indent=2)

            # 复制 JSON 文件
            if json_dir and os.path.isdir(json_dir):
                components = sim_config.get("Components", [])
                copy_json_files_to_task_dir(task_dir, json_dir, components, cif_path)

            success_count += 1
            logger.debug(f"成功生成任务: mc{idx} ({framework_name})")

        except Exception as e:
            logger.error(f"生成任务 mc{idx} ({framework_name}) 失败: {e}")
            logger.debug(traceback.format_exc())
            fail_count += 1

    return success_count, fail_count


def main():
    parser = argparse.ArgumentParser(description='RASPA3 高通量计算输入文件生成器')
    parser.add_argument('--config', '-c', help='配置文件路径')
    parser.add_argument('--csv', help='CSV 文件路径')
    parser.add_argument('--framework-column', help='框架名称列名')
    parser.add_argument('--output-dir', help='输出目录')
    parser.add_argument('--template', help='simulation.json 模板路径')
    parser.add_argument('--json-dir', help='JSON 文件目录')
    parser.add_argument('--cif-base-path', help='CIF 文件基础路径')
    parser.add_argument('--cutoff', type=float, default=12.0, help='截断半径')
    parser.add_argument('--void-fraction', type=float, default=0.5, help='默认孔隙率')

    args = parser.parse_args()

    # 从配置文件或命令行参数获取设置
    if args.config:
        config = load_config(args.config)
        env = config.get('environment', {})
        calc = config.get('calculation', {})

        csv_path = args.csv or calc.get('csv_file_path')
        framework_column = args.framework_column or calc.get('framework_column')
        output_dir = args.output_dir or os.path.join(
            env.get('work_dir', '.'),
            calc.get('output_directory', 'output')
        )
        template_path = args.template or env.get('raspa3_template_path')
        json_dir = args.json_dir or env.get('raspa3_json_dir')
        cif_base_path = args.cif_base_path or env.get('raspa3_cif_base_path')
        cutoff = args.cutoff or calc.get('cutoff_radius', 12.0)
    else:
        csv_path = args.csv
        framework_column = args.framework_column
        output_dir = args.output_dir
        template_path = args.template
        json_dir = args.json_dir
        cif_base_path = args.cif_base_path
        cutoff = args.cutoff

    # 验证必需参数
    if not csv_path:
        logger.error("请指定 CSV 文件路径 (--csv 或在配置文件中设置)")
        sys.exit(1)
    if not framework_column:
        logger.error("请指定框架名称列 (--framework-column 或在配置文件中设置)")
        sys.exit(1)
    if not output_dir:
        logger.error("请指定输出目录 (--output-dir 或在配置文件中设置)")
        sys.exit(1)
    if not template_path:
        logger.error("请指定模板路径 (--template 或在配置文件中设置 raspa3_template_path)")
        sys.exit(1)
    if not cif_base_path:
        logger.error("请指定 CIF 基础路径 (--cif-base-path 或在配置文件中设置 raspa3_cif_base_path)")
        sys.exit(1)

    logger.info("=== RASPA3 任务生成器 ===")
    logger.info(f"CSV 文件: {csv_path}")
    logger.info(f"框架列名: {framework_column}")
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"模板文件: {template_path}")
    logger.info(f"JSON 目录: {json_dir}")
    logger.info(f"CIF 基础路径: {cif_base_path}")
    logger.info(f"截断半径: {cutoff}")

    try:
        # 读取框架列表
        frameworks = get_frameworks_from_csv(csv_path, framework_column)

        # 生成任务
        success, fail = generate_raspa3_tasks(
            frameworks=frameworks,
            output_dir=output_dir,
            template_path=template_path,
            json_dir=json_dir,
            cif_base_path=cif_base_path,
            cutoff=cutoff,
            void_fraction=args.void_fraction
        )

        logger.info(f"\n=== 生成完成 ===")
        logger.info(f"成功: {success} 个")
        logger.info(f"失败: {fail} 个")
        logger.info(f"输出目录: {output_dir}")

        if fail > 0:
            sys.exit(1)

    except Exception as e:
        logger.error(f"生成失败: {e}")
        logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
