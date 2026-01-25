#!/usr/bin/env python3
import os
import math
import sys
import logging
import json
import re
import traceback
import pandas as pd
import numpy as np

# 导入必需的gemmi库（用于精确的CIF文件处理）
try:
    import gemmi
except ImportError:
    raise ImportError(
        "必需的gemmi库未安装。请安装gemmi库：\n"
        "pip install gemmi\n"
        "或者访问：https://gemmi.readthedocs.io/en/latest/install.html"
    )

# 配置日志系统
def setup_logging():
    """设置日志系统：使用模块命名 Logger，不干扰全局配置"""
    logger = logging.getLogger(__name__)
    return logger

# 初始化日志系统
logger = setup_logging()

def check_structure_files(framework_name, cif_dir):
    """检查结构文件是否存在，如果不存在则提示用户重新输入"""
    while True:
        # 处理框架名称，确保它没有.cif后缀
        if framework_name.lower().endswith('.cif'):
            framework_name = framework_name[:-4]  # 移除.cif后缀

        # 使用用户指定的CIF目录
        cif_file = os.path.join(cif_dir, f"{framework_name}.cif")

        # 检查文件是否存在
        if os.path.exists(cif_file):
            logger.info(f"找到框架 {framework_name} 的CIF文件: {cif_file}")
            return cif_file

        # 尝试其他可能的文件名形式
        alternative_files = [
            os.path.join(cif_dir, f"{framework_name.upper()}.cif"),  # 全大写
            os.path.join(cif_dir, f"{framework_name.lower()}.cif"),  # 全小写
            os.path.join(cif_dir, f"{framework_name}")  # 无后缀
        ]

        for alt_file in alternative_files:
            if os.path.exists(alt_file):
                logger.info(f"找到框架 {framework_name} 的替代CIF文件: {alt_file}")
                return alt_file

        # 列出目录中的所有文件，便于调试
        if os.path.exists(cif_dir):
            logger.debug(f"CIF目录 {cif_dir} 中的文件:")
            for file in os.listdir(cif_dir):
                logger.debug(f"  - {file}")

        logger.warning(f"找不到框架 {framework_name} 的CIF文件: {cif_file}")
        retry = input("是否重新指定CIF文件目录? (y/n): ").strip().lower()
        if retry != 'y':
            return None

        cif_dir = input("请输入CIF文件目录路径: ").strip()
        if not cif_dir:
            logger.error("目录路径不能为空")
            return None

def get_cif_cell_parameters(cif_file, cutoff=12.0):
    """从 CIF 文件中提取晶胞参数并使用新的算法计算单位晶胞数"""
    try:
        logger.info(f"使用新的calculate_UnitCells算法处理CIF文件: {cif_file}")
        
        # 使用新的算法计算单位晶胞数
        unit_cells_str = calculate_UnitCells(cif_file, cutoff)
        unit_cells = list(map(int, unit_cells_str.split()))
        
        logger.info(f"新算法计算结果: {unit_cells[0]} x {unit_cells[1]} x {unit_cells[2]}")
        
        return unit_cells
        
    except Exception as e:
        logger.error(f"新算法计算失败，使用后备方法: {e}")
        
        # 后备方法：使用原来的简单计算
        try:
            params = read_cif_params(cif_file)
            if params is None:
                return None
                
            a, b, c, alpha, beta, gamma = params
            
            # 简单计算方法作为后备
            unit_cells_a = max(1, int(2 * cutoff / a) + 1)
            unit_cells_b = max(1, int(2 * cutoff / b) + 1) 
            unit_cells_c = max(1, int(2 * cutoff / c) + 1)
            
            logger.info(f"后备方法计算结果: {unit_cells_a} x {unit_cells_b} x {unit_cells_c}")
            
            return [unit_cells_a, unit_cells_b, unit_cells_c]
            
        except Exception as fallback_error:
            logger.error(f"后备方法也失败: {fallback_error}")
            return None

def calculate_perpendicular_widths(cif_filename: str) -> tuple:
    """
    Calculate the perpendicular widths of the unit cell using precise vector calculations.
    RASPA considers the perpendicular directions as the directions perpendicular to the `ab`,
    `bc`, and `ca` planes. Thus, the directions depend on the crystallographic vectors `a`, `b`,
    and `c`.
    The length in the perpendicular directions are the projections of the crystallographic vectors
    on the vectors `a x b`, `b x c`, and `c x a`. (here `x` means cross product)

    This implementation uses proper vector mathematics for maximum accuracy.
    """
    # Read data from CIF file using gemmi
    cif = gemmi.cif.read_file(cif_filename).sole_block()
    a = float(cif.find_value('_cell_length_a').split('(')[0])
    b = float(cif.find_value('_cell_length_b').split('(')[0])
    c = float(cif.find_value('_cell_length_c').split('(')[0])
    beta = float(cif.find_value('_cell_angle_beta').split('(')[0]) * np.pi / 180.0
    gamma = float(cif.find_value('_cell_angle_gamma').split('(')[0]) * np.pi / 180.0
    alpha = float(cif.find_value('_cell_angle_alpha').split('(')[0]) * np.pi / 180.0

    # Calculate the nu value
    nu = (np.cos(alpha) - np.cos(gamma) * np.cos(beta)) / np.sin(gamma)

    # Build the transformation matrix as a numpy array
    CellBox = np.array([[a, 0.0, 0.0],
                        [b * np.cos(gamma), b * np.sin(gamma), 0.0],
                        [c * np.cos(beta), c * nu, c * np.sqrt(1.0 - np.cos(beta)**2 - nu**2)]])

    # Calculate the cross products
    axb = np.cross(CellBox[0], CellBox[1])
    bxc = np.cross(CellBox[1], CellBox[2])
    cxa = np.cross(CellBox[2], CellBox[0])

    # Calculate the volume of the unit cell
    V = np.dot(np.cross(CellBox[0], CellBox[1]), CellBox[2])

    # Calculate perpendicular widths
    p_width_1 = V / np.linalg.norm(bxc)
    p_width_2 = V / np.linalg.norm(cxa)
    p_width_3 = V / np.linalg.norm(axb)

    logger.info(f"晶胞体积: {V:.2f} Å³")
    logger.info(f"垂直宽度: {p_width_1:.2f}, {p_width_2:.2f}, {p_width_3:.2f} Å")

    return p_width_1, p_width_2, p_width_3

def calculate_UnitCells(cif_filename, cutoff):
    """
    Calculate the number of unit cell repetitions so that all supercell lengths are larger than
    twice the interaction potential cut-off radius.

    Parameters
    ----------
    cif_filename : str
        Name of the cif file.
    cutoff : float
        Cut-off radius.

    Returns
    -------
    unit_cells : str
        String with the number of unit cells in each direction.
    """
    try:
        # Calculate the perpendicular widths using improved algorithm
        p_width_1, p_width_2, p_width_3 = calculate_perpendicular_widths(cif_filename)

        # Calculate UnitCells array
        uc_array = np.ceil(2.0 * cutoff / np.array([p_width_1, p_width_2, p_width_3])).astype(int)
        unit_cells = ' '.join(map(str, uc_array))

        logger.info(f"计算单位晶胞数: {uc_array[0]} x {uc_array[1]} x {uc_array[2]}")

        return unit_cells
        
    except Exception as e:
        logger.error(f"计算单位晶胞数时出错: {str(e)}")
        raise

def read_cif_params(cif_file):
    """从CIF文件中读取晶胞参数，使用直接的读取方法

    Args:
        cif_file (str): CIF文件路径

    Returns:
        tuple: 包含(a, b, c, alpha, beta, gamma)的元组，失败时返回None
    """
    try:
        # 检查文件是否存在
        if not os.path.isfile(cif_file):
            logger.error(f"CIF文件不存在: {cif_file}")
            return None

        # 读取CIF文件
        with open(cif_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 直接从文件中提取晶胞参数
        a = b = c = alpha = beta = gamma = None
        for line in lines:
            if line.startswith('_cell_length_a'):
                a = float(line.split()[-1].strip().split('(')[0])
            elif line.startswith('_cell_length_b'):
                b = float(line.split()[-1].strip().split('(')[0])
            elif line.startswith('_cell_length_c'):
                c = float(line.split()[-1].strip().split('(')[0])
            elif line.startswith('_cell_angle_alpha'):
                alpha = float(line.split()[-1].strip().split('(')[0])
            elif line.startswith('_cell_angle_beta'):
                beta = float(line.split()[-1].strip().split('(')[0])
            elif line.startswith('_cell_angle_gamma'):
                gamma = float(line.split()[-1].strip().split('(')[0])
            if a and b and c and alpha and beta and gamma:
                break

        # 检查所有必需参数是否已提取
        if a and b and c and alpha and beta and gamma:
            logger.info(f"从CIF文件成功提取晶胞参数: a={a}, b={b}, c={c}, "
                      f"alpha={alpha}, beta={beta}, gamma={gamma}")
            return a, b, c, alpha, beta, gamma
        else:
            missing = []
            if not a: missing.append("a")
            if not b: missing.append("b")
            if not c: missing.append("c")
            if not alpha: missing.append("alpha")
            if not beta: missing.append("beta")
            if not gamma: missing.append("gamma")
            logger.error(f"CIF文件缺少参数: {', '.join(missing)}")
            return None

    except Exception as e:
        logger.error(f"读取CIF文件时出错: {str(e)}")
        return None

def validate_crystal_parameters(a, b, c, alpha, beta, gamma):
    """验证晶胞参数的有效性"""
    errors = []

    # 检查长度参数
    if any(not isinstance(x, (int, float)) for x in [a, b, c]):
        errors.append("晶胞长度必须为数值")
    elif any(x <= 0 for x in [a, b, c]):
        errors.append("晶胞长度必须为正数")

    # 检查角度参数
    if any(not isinstance(x, (int, float)) for x in [alpha, beta, gamma]):
        errors.append("晶胞角度必须为数值")
    elif any(not 0 < x < 180 for x in [alpha, beta, gamma]):
        errors.append("晶胞角度必须在0到180度之间")

    # 返回错误列表（如果没有错误则为空）
    return errors

def calculate_unit_cells(a, b, c, alpha, beta, gamma, r_cut):
    """计算所需的单位晶胞数，使用更直接的计算方法"""
    # 基本参数验证
    validation_errors = validate_crystal_parameters(a, b, c, alpha, beta, gamma)
    if validation_errors:
        for error in validation_errors:
            logger.error(error)
        raise ValueError("; ".join(validation_errors))

    if not isinstance(r_cut, (int, float)) or r_cut <= 0:
        logger.error("截断半径必须为正数")
        raise ValueError("截断半径必须为正数")

    try:
        # 将角度从度转换为弧度
        alpha_rad = math.radians(alpha)
        beta_rad = math.radians(beta)
        gamma_rad = math.radians(gamma)

        # 计算晶胞体积
        V = a * b * c * (1 + 2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad) -
                         (math.cos(alpha_rad))**2 - (math.cos(beta_rad))**2 - (math.cos(gamma_rad))**2) ** 0.5

        if V <= 0:
            logger.error("无效的晶胞参数：体积计算结果为负数或零")
            raise ValueError("无效的晶胞参数：体积计算结果为负数或零")

        # 计算各个面的表面积
        base_area_x = b * c * math.sin(alpha_rad)
        base_area_y = a * c * math.sin(beta_rad)
        base_area_z = a * b * math.sin(gamma_rad)

        if any(area <= 0 for area in [base_area_x, base_area_y, base_area_z]):
            logger.error("无效的晶胞参数：一个或多个基底面积为零或负数")
            raise ValueError("无效的晶胞参数：一个或多个基底面积为零或负数")

        # 计算各个方向的垂直高度
        perpendicular_length_x = V / base_area_x
        perpendicular_length_y = V / base_area_y
        perpendicular_length_z = V / base_area_z

        # 计算各方向所需单位晶胞数
        unit_cell_x = max(1, math.ceil(2 * r_cut / perpendicular_length_x))
        unit_cell_y = max(1, math.ceil(2 * r_cut / perpendicular_length_y))
        unit_cell_z = max(1, math.ceil(2 * r_cut / perpendicular_length_z))

        # 记录调试信息
        logger.debug(f"晶胞参数: a={a:.3f}, b={b:.3f}, c={c:.3f} Å")
        logger.debug(f"晶胞角度: α={alpha:.2f}°, β={beta:.2f}°, γ={gamma:.2f}°")
        logger.debug(f"晶胞体积: {V:.2f} Å³")
        logger.debug(f"垂直高度: {perpendicular_length_x:.2f}, {perpendicular_length_y:.2f}, {perpendicular_length_z:.2f} Å")
        logger.debug(f"单位晶胞数: {unit_cell_x} x {unit_cell_y} x {unit_cell_z}")

        # 添加一个打印语句，用于自动化脚本解析
        logger.debug(f"UNIT_CELLS_DEBUG {unit_cell_x} {unit_cell_y} {unit_cell_z}")

        return unit_cell_x, unit_cell_y, unit_cell_z, V

    except Exception as e:
        logger.error(f"计算单位晶胞时出错: {str(e)}")
        # 重新抛出异常以便调用者处理
        raise

def get_framework_names(csv_file, column_number):
    """从CSV文件中读取框架名称"""
    try:
        # 验证输入参数
        if not os.path.exists(csv_file):
            logger.error(f"CSV文件不存在: {csv_file}")
            return []

        try:
            column_number = int(column_number)
        except ValueError:
            logger.error(f"列号必须为整数: {column_number}")
            return []

        # 读取CSV文件
        try:
            df = pd.read_csv(csv_file)
        except Exception as e:
            logger.error(f"读取CSV文件失败: {str(e)}")
            return []

        # 检查列号是否有效
        if column_number < 1 or column_number > len(df.columns):
            logger.error(f"列号 {column_number} 超出范围 (1-{len(df.columns)})")
            return []

        column_name = df.columns[int(column_number) - 1]  # 转换列号为列名
        logger.info(f"使用列: {column_name}")

        # 检查该列是否存在
        if column_name not in df.columns:
            logger.error(f"列名 {column_name} 不存在于CSV文件中")
            return []

        framework_names = df[column_name].dropna().tolist()
        # 过滤并返回有效的框架名称
        valid_names = [str(name).strip() for name in framework_names if str(name).strip()]

        logger.info(f"从CSV文件中找到 {len(valid_names)} 个有效框架名称")

        # 将结果打印到标准输出，供shell脚本读取
        for name in valid_names:
            print(name)

        return valid_names
    except Exception as e:
        logger.error(f"读取CSV文件时出错: {str(e)}")
        return []

def get_void_fraction_from_csv(framework_name, csv_file=None, void_fraction_column=None, framework_column=None):
    """从CSV文件中获取孔隙率

    Args:
        framework_name (str): 框架名称
        csv_file (str, optional): CSV文件路径. 默认为None.
        void_fraction_column (str or int, optional): 包含孔隙率的列名或列号. 默认为None.
        framework_column (str, optional): 框架名称列名，强制使用此列. 默认为None.

    Returns:
        float: 孔隙率值，如果找不到则返回None
    """
    if csv_file is None or void_fraction_column is None:
        return None

    try:
        # 检查CSV文件是否存在
        if not os.path.exists(csv_file):
            logger.warning(f"CSV文件不存在: {csv_file}")
            return None

        # 读取CSV文件，处理BOM编码问题
        try:
            df = pd.read_csv(csv_file, encoding='utf-8-sig')  # utf-8-sig可以自动处理BOM
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(csv_file, encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(csv_file, encoding='gbk')

        # 如果指定了framework_column，强制使用该列
        if framework_column is not None:
            if framework_column in df.columns:
                framework_column_name = framework_column
                logger.info(f"使用指定的框架列名: {framework_column_name}")
            else:
                logger.error(f"指定的框架列名 '{framework_column}' 在CSV文件中不存在")
                logger.info(f"CSV文件中可用的列名: {list(df.columns)}")
                return None
        else:
            # 如果没有指定，使用默认查找逻辑（保持向后兼容）
            framework_column_name = None
            # 首先尝试查找 refcode 列
            if 'refcode' in df.columns:
                framework_column_name = 'refcode'
            # 如果有coreid列，优先使用它
            elif 'coreid' in df.columns:
                framework_column_name = 'coreid'
            else:
                # 如果没有refcode和coreid列，尝试查找其他可能的框架名称列
                for col in df.columns:
                    if any(keyword in col.lower() for keyword in ['framework', 'name', 'structure', '框架', '名称', '结构', 'refcode', 'coreid']):
                        framework_column_name = col
                        break

            if framework_column_name is None:
                logger.warning(f"无法在CSV文件中找到框架名称列")
                return None

        # 获取孔隙率列
        void_fraction_col = None
        if isinstance(void_fraction_column, int):
            if 0 <= void_fraction_column < len(df.columns):
                void_fraction_col = df.columns[void_fraction_column]
            else:
                logger.warning(f"列号超出范围: {void_fraction_column}")
                return None
        else:  # 字符串
            if void_fraction_column in df.columns:
                void_fraction_col = void_fraction_column
            else:
                logger.warning(f"在CSV文件中找不到列: {void_fraction_column}")
                return None

        # 处理框架名称，确保它没有.cif后缀
        clean_framework_name = framework_name
        if clean_framework_name.lower().endswith('.cif'):
            clean_framework_name = clean_framework_name[:-4]  # 移除.cif后缀

        # 查找框架对应的孔隙率
        framework_row = df[df[framework_column_name] == clean_framework_name]
        if framework_row.empty:
            # 尝试其他可能的名称形式
            alternative_names = [
                framework_name,  # 原始名称
                clean_framework_name.upper(),  # 全大写
                clean_framework_name.lower()   # 全小写
            ]

            for alt_name in alternative_names:
                framework_row = df[df[framework_column_name] == alt_name]
                if not framework_row.empty:
                    logger.info(f"使用替代名称 {alt_name} 找到框架在CSV文件中")
                    break

            if framework_row.empty:
                logger.info(f"在CSV文件中找不到框架: {framework_name}，将使用默认孔隙率")
                return None

        # 获取孔隙率值
        void_fraction = framework_row[void_fraction_col].iloc[0]
        if pd.isna(void_fraction):
            logger.warning(f"框架 {framework_name} 的孔隙率值为空")
            return None

        try:
            void_fraction = float(void_fraction)
            logger.info(f"从CSV文件获取到框架 {framework_name} 的孔隙率: {void_fraction}")
            return void_fraction
        except (ValueError, TypeError):
            logger.warning(f"无法将孔隙率值转换为浮点数: {void_fraction}")
            return None

    except Exception as e:
        logger.warning(f"从CSV文件获取孔隙率时出错: {str(e)}")
        return None

def process_structure_file(structure_file, r_cut=12.0, result_cache=None, csv_file=None, void_fraction_column=None, framework_column=None):
    """处理结构文件（支持wei和cif格式）并返回计算结果

    Args:
        structure_file (str): 结构文件路径（wei或cif格式）
        r_cut (float, optional): 截断半径. 默认为12.0.
        result_cache (dict, optional): 缓存字典. 默认为None.
        csv_file (str, optional): 包含孔隙率的CSV文件路径. 默认为None.
        void_fraction_column (str or int, optional): 包含孔隙率的列名或列号. 默认为None.
        framework_column (str, optional): 框架名称列名，强制使用此列. 默认为None.

    Returns:
        tuple: (success, unit_cells, void_fraction)
    """
    # 使用缓存避免重复计算
    if result_cache is not None:
        cache_key = f"{structure_file}_{r_cut}"
        if cache_key in result_cache:
            logger.debug(f"使用缓存结果: {cache_key}")
            return result_cache[cache_key]

    try:
        # 检查截断半径参数
        try:
            r_cut = float(r_cut)
            if r_cut <= 0:
                logger.error(f"截断半径必须为正数: {r_cut}")
                return False, None, None
        except ValueError:
            logger.error(f"截断半径必须为数值: {r_cut}")
            return False, None, None

        # 判断文件类型
        file_ext = os.path.splitext(structure_file)[1].lower()

        # 获取框架名称
        framework_name = os.path.splitext(os.path.basename(structure_file))[0]
        # 处理框架名称，确保它没有.cif后缀
        if framework_name.lower().endswith('.cif'):
            framework_name = framework_name[:-4]  # 移除.cif后缀
        logger.info(f"处理框架: {framework_name}")

        # 尝试从CSV文件获取孔隙率
        csv_void_fraction = None
        if csv_file is not None and void_fraction_column is not None:
            csv_void_fraction = get_void_fraction_from_csv(framework_name, csv_file, void_fraction_column, framework_column)
            if csv_void_fraction is not None:
                logger.info(f"使用从CSV文件获取的孔隙率: {csv_void_fraction}")
                helium_void_fraction = csv_void_fraction

        # 根据不同文件类型处理
        if file_ext == '.cif':
            # 直接使用新的CIF处理函数获取单位晶胞数
            unit_cells = get_cif_cell_parameters(structure_file, r_cut)
            if unit_cells is None:
                logger.error(f"从CIF文件提取参数失败: {structure_file}")
                return False, None, None

            # 如果没有从CSV获取到孔隙率，使用默认值
            if csv_void_fraction is None:
                helium_void_fraction = 0.5  # 使用默认值
                logger.info(f"CIF文件未从CSV获取到孔隙率，使用默认void_fraction: {helium_void_fraction}")

        else:
            logger.error(f"不支持的文件类型: {file_ext}")
            return False, None, None

        # 设置返回结果
        result = (True, (unit_cells[0], unit_cells[1], unit_cells[2]), helium_void_fraction)

        # 如果有提供缓存，则保存结果
        if result_cache is not None:
            result_cache[cache_key] = result

        # 返回结果
        return result

    except Exception as e:
        logger.error(f"处理结构文件时出错: {str(e)}")
        return False, None, None

# 删除了process_wei_file函数，因为不再需要wei文件支持

def save_cache(cache, cache_file="params_cache.json"):
    """将计算缓存保存到文件"""
    try:
        # 将缓存转换为可序列化的格式
        serializable_cache = {}
        for key, value in cache.items():
            success, unit_cells, void_fraction = value
            if unit_cells:
                serializable_cache[key] = {
                    "success": success,
                    "unit_cells": list(unit_cells) if unit_cells else None,
                    "void_fraction": void_fraction
                }

        # 保存到文件
        with open(cache_file, 'w') as f:
            json.dump(serializable_cache, f)

        logger.debug(f"缓存已保存到: {cache_file}")
        return True
    except Exception as e:
        logger.error(f"保存缓存失败: {str(e)}")
        return False

def load_cache(cache_file="params_cache.json"):
    """从文件加载计算缓存"""
    if not os.path.exists(cache_file):
        return {}

    try:
        with open(cache_file, 'r') as f:
            serialized_cache = json.load(f)

        # 将序列化的格式转换回原始格式
        cache = {}
        for key, value in serialized_cache.items():
            success = value.get("success", False)
            unit_cells = tuple(value.get("unit_cells", [None, None, None]))
            void_fraction = value.get("void_fraction")
            cache[key] = (success, unit_cells, void_fraction)

        logger.debug(f"已从 {cache_file} 加载 {len(cache)} 个缓存条目")
        return cache
    except Exception as e:
        logger.error(f"加载缓存失败: {str(e)}")
        return {}

def main():
    """主函数"""
    # 加载计算缓存
    cache = load_cache()

    try:
        # 解析命令行参数
        import argparse
        parser = argparse.ArgumentParser(description='计算RASPA模拟参数')
        parser.add_argument('input', help='CSV文件或结构文件路径')
        parser.add_argument('--column', '-c', help='CSV文件中框架名称列的列号')
        parser.add_argument('--void-csv', help='包含孔隙率的CSV文件路径')
        parser.add_argument('--void-column', help='空隙率列的列名或列号')
        parser.add_argument('--framework-column', help='框架名称列的列名')
        parser.add_argument('--cutoff', '-r', type=float, default=12.0, help='截断半径，默认为12.0')

        # 兼容旧的命令行参数格式
        if len(sys.argv) == 3 and not sys.argv[1].startswith('-') and not sys.argv[2].startswith('-'):
            args = parser.parse_args([sys.argv[1], '--column', sys.argv[2]])
        else:
            args = parser.parse_args()

        # 处理CSV文件模式
        if args.column is not None:
            csv_file = args.input
            column_number = args.column
            get_framework_names(csv_file, column_number)
        # 处理单个结构文件模式
        else:
            structure_file = args.input
            success, unit_cells, void_fraction = process_structure_file(
                structure_file,
                r_cut=args.cutoff,
                result_cache=cache,
                csv_file=args.void_csv,
                void_fraction_column=args.void_column,
                framework_column=args.framework_column
            )

            if success and unit_cells:
                # 使用标准格式输出，供参数筛选解析
                print(f"UNIT_CELLS {unit_cells[0]} {unit_cells[1]} {unit_cells[2]}")
                if void_fraction is not None:
                    print(f"VOID_FRACTION {void_fraction}")
            else:
                logger.error(f"处理结构文件失败: {structure_file}")
                sys.exit(1)

        # 保存更新后的缓存
        save_cache(cache)

    except Exception as e:
        logger.error(f"程序执行出错: {str(e)}")
        logger.debug(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
