#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RASPA2到RASPA3分子定义文件转换器

此脚本用于将RASPA2格式的分子定义文件转换为RASPA3的JSON格式。
它会读取.def格式的分子定义文件（如o-xylene.def, m-xylene.def, p-xylene.def），
并生成符合RASPA3格式要求的.json文件（类似于N2.json）。

用法:
    单文件模式:
        python convert_molecule.py <input_def_file> [output_json_file]
    
    批量处理模式:
        python convert_molecule.py -d <input_directory> [output_directory]
        python convert_molecule.py --dir <input_directory> [output_directory]

参数:
    input_def_file   - RASPA2格式的分子定义文件(.def)
    output_json_file - 输出的RASPA3 JSON格式文件 (默认: 输入文件名.json)
    
    -d, --dir        - 启用目录模式，处理指定目录中的所有.def文件
    input_directory  - 包含.def文件的输入目录
    output_directory - 输出.json文件的目录 (默认: 与输入目录相同)

示例:
    python convert_molecule.py o-xylene.def
    python convert_molecule.py m-xylene.def m-xylene.json
    python convert_molecule.py -d ./molecules
    python convert_molecule.py --dir ./molecules ./output
"""

import json
import os
import sys
import re
import traceback
import glob
import argparse
from datetime import datetime

# 设置调试模式
DEBUG = False

def debug_print(message):
    """如果DEBUG为True，则打印调试信息"""
    if DEBUG:
        print(f"[DEBUG] {message}")

def print_separator():
    """打印分隔行"""
    print("-" * 60)

def read_molecule_def(filename):
    """读取RASPA2格式的分子定义文件"""
    
    print(f"读取分子定义文件: {filename}")
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"读取文件 {filename} 时出错: {str(e)}")
        return None
    
    # 拆分文件内容行，并移除注释
    lines = []
    for line in content.split('\n'):
        # 移除注释部分
        if '#' in line:
            line = line[:line.index('#')]
        line = line.strip()
        if line:  # 只保留非空行
            lines.append(line)
    
    debug_print(f"处理后的有效行数: {len(lines)}")
    
    # 解析关键数据
    molecule = {}
    
    # 1. 解析临界常数
    try:
        critical_temperature = float(lines[0])
        critical_pressure = float(lines[1])
        acentric_factor = float(lines[2])
        
        molecule["CriticalTemperature"] = critical_temperature
        molecule["CriticalPressure"] = critical_pressure
        molecule["AcentricFactor"] = acentric_factor
        
        debug_print(f"临界常数: {critical_temperature} K, {critical_pressure} Pa, {acentric_factor}")
    except (ValueError, IndexError) as e:
        print(f"解析临界常数时出错: {str(e)}")
        return None
    
    # 2. 解析原子数量和分子类型
    try:
        # 查找"Number Of Atoms"行及其后的数字
        i = 3
        while i < len(lines) and not re.match(r'^\d+$', lines[i]):
            i += 1
        
        if i >= len(lines):
            raise ValueError("未找到原子数量")
        
        num_atoms = int(lines[i])
        debug_print(f"原子数量: {num_atoms}")
        
        # 查找"Number Of Groups"行及其后的数字
        i += 1
        while i < len(lines) and not re.match(r'^\d+$', lines[i]):
            i += 1
        
        if i >= len(lines):
            raise ValueError("未找到组数量")
        
        num_groups = int(lines[i])
        debug_print(f"组数量: {num_groups}")
        
        # 获取分子类型（通常是刚性的）
        i += 1
        while i < len(lines) and (re.match(r'^\d+$', lines[i]) or len(lines[i].split()) > 1):
            i += 1
            
        if i >= len(lines):
            raise ValueError("未找到分子类型")
            
        molecule_type = lines[i].lower()  # 例如: rigid
        molecule["Type"] = molecule_type
        debug_print(f"分子类型: {molecule_type}")
        
        # 找到"number of atoms"后的再次确认的原子数量
        i += 1
        while i < len(lines) and not re.match(r'^\d+$', lines[i]):
            i += 1
        
        if i >= len(lines):
            raise ValueError("未找到第二次原子数量确认")
        
        # 二次确认原子数量
        confirmed_num_atoms = int(lines[i])
        if confirmed_num_atoms != num_atoms:
            print(f"警告: 原子数量不一致 ({num_atoms} vs {confirmed_num_atoms})")
            num_atoms = confirmed_num_atoms  # 使用后确认的数量
        
        # 读取原子位置
        atom_start_index = i + 1
        debug_print(f"原子坐标起始行索引: {atom_start_index}")
        
        atoms = []
        
        for j in range(atom_start_index, atom_start_index + num_atoms):
            if j >= len(lines):
                raise ValueError(f"原子定义不足，预期 {num_atoms} 个，实际找到 {j - atom_start_index} 个")
            
            parts = lines[j].split()
            if len(parts) < 5:
                raise ValueError(f"原子定义格式不正确: {lines[j]}")
            
            index = int(parts[0])
            atom_type = parts[1]
            x = float(parts[2])
            y = float(parts[3])
            z = float(parts[4])
            
            atoms.append([atom_type, [x, y, z]])
            debug_print(f"原子 {index}: {atom_type} at [{x}, {y}, {z}]")
        
        molecule["pseudoAtoms"] = atoms
        
        # 在"Chiral centers"或"Bond stretch"之后的部分寻找键信息
        bond_section_start = atom_start_index + num_atoms
        
        # 跳过Chiral centers行
        while bond_section_start < len(lines) and "Bond stretch:" not in lines[bond_section_start]:
            debug_print(f"跳过行: {lines[bond_section_start]}")
            bond_section_start += 1
        
        if bond_section_start >= len(lines):
            print("警告: 未找到键定义部分")
            molecule["Bonds"] = []
        else:
            debug_print(f"键定义起始行索引: {bond_section_start}, 内容: {lines[bond_section_start]}")
            
            # 读取键信息
            bonds = []
            for j in range(bond_section_start + 1, len(lines)):
                # 如果遇到新的部分标记，如"Number of config moves"，说明键部分已结束
                if j >= len(lines) or lines[j].startswith("#") or "Number of config moves" in lines[j]:
                    debug_print(f"键定义结束于行 {j}")
                    break
                
                parts = lines[j].split()
                if len(parts) >= 3:  # 至少有两个原子索引和一个键类型
                    atom1 = int(parts[0])
                    atom2 = int(parts[1])
                    # RASPA3只需要原子索引，不需要键类型
                    bonds.append([atom1, atom2])
                    debug_print(f"键: {atom1}-{atom2}")
            
            molecule["Bonds"] = bonds
    
    except Exception as e:
        print(f"解析文件结构时出错: {str(e)}")
        if DEBUG:
            traceback.print_exc()
        return None
    
    return molecule

def write_molecule_json(molecule, output_file):
    """将分子对象写入JSON文件"""
    
    print(f"写入分子JSON文件: {output_file}")
    
    try:
        # 创建一个自定义格式的JSON字符串，以匹配N2.json的格式
        json_content = "{\n"
        json_content += f'  "CriticalTemperature" : {molecule["CriticalTemperature"]},\n'
        json_content += f'  "CriticalPressure" : {molecule["CriticalPressure"]},\n'
        json_content += f'  "AcentricFactor" : {molecule["AcentricFactor"]},\n'
        json_content += f'  "Type" : "{molecule["Type"]}",\n'
        
        # 添加pseudoAtoms部分，完全匹配N2.json的格式
        json_content += '  "pseudoAtoms" : \n    [\n'
        for i, atom in enumerate(molecule["pseudoAtoms"]):
            atom_type = atom[0]
            x, y, z = atom[1]
            
            # 设置格式，保持一致的空格
            atom_str = f'      ["{atom_type}",  ['
            
            # 为了使坐标对齐，增加适当的空格
            x_str = f"{x}"
            y_str = f"{y}"
            z_str = f"{z}"
            
            # 确保坐标有一致的对齐，x和y后面有空格，z后面没有
            if len(atom_type) <= 5:  # 对于短的原子名称，增加空格
                atom_str += f"{x_str}, {y_str},  {z_str}"
            else:  # 对于长的原子名称，减少空格
                atom_str += f"{x_str}, {y_str}, {z_str}"
            
            atom_str += "]]"
            if i < len(molecule["pseudoAtoms"]) - 1:
                atom_str += ','
            json_content += atom_str + '\n'
        json_content += '    ],\n'
        
        # 添加Bonds部分，每3个一行
        json_content += '  "Bonds" : ['
        for i, bond in enumerate(molecule["Bonds"]):
            if i > 0 and i % 3 == 0:  # 每3个键换一行
                json_content += '\n           '
            bond_str = f'[{bond[0]},{bond[1]}]'
            if i < len(molecule["Bonds"]) - 1:
                bond_str += ', '
            json_content += bond_str
        json_content += ']\n'
        
        # 添加尾部空格，与N2.json一致
        json_content += '}   \n'
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 写入文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(json_content)
        
        file_size = os.path.getsize(output_file) / 1024  # 转换为KB
        print(f"已成功创建RASPA3分子文件: {output_file} (大小: {file_size:.2f} KB)")
        return True
    except Exception as e:
        print(f"写入JSON文件 {output_file} 时出错: {str(e)}")
        if DEBUG:
            traceback.print_exc()
        return False

def convert_single_file(input_file, output_file=None):
    """转换单个.def文件为.json格式"""
    
    if not os.path.exists(input_file):
        print(f"错误: 文件 {input_file} 不存在")
        return False
    
    if not output_file:
        # 用相同的文件名，但扩展名改为.json
        base_name = os.path.splitext(input_file)[0]
        output_file = f"{base_name}.json"
    
    print_separator()
    print(f"处理文件: {os.path.basename(input_file)}")
    print(f"输入: {os.path.abspath(input_file)}")
    print(f"输出: {os.path.abspath(output_file)}")
    
    # 读取并转换分子
    molecule = read_molecule_def(input_file)
    
    if molecule:
        print("分子结构信息:")
        print(f"临界温度: {molecule['CriticalTemperature']} K")
        print(f"临界压力: {molecule['CriticalPressure']} Pa")
        print(f"偏心因子: {molecule['AcentricFactor']}")
        print(f"分子类型: {molecule['Type']}")
        print(f"伪原子数量: {len(molecule['pseudoAtoms'])}")
        print(f"键数量: {len(molecule['Bonds'])}")
        
        # 写入JSON文件
        return write_molecule_json(molecule, output_file)
    else:
        print(f"未能读取分子定义文件: {input_file}")
        return False

def process_directory(input_dir, output_dir=None):
    """处理目录中的所有.def文件"""
    
    if not os.path.exists(input_dir) or not os.path.isdir(input_dir):
        print(f"错误: 目录 {input_dir} 不存在或不是有效的目录")
        return False
    
    # 如果未指定输出目录，使用输入目录
    if not output_dir:
        output_dir = input_dir
    
    # 确保输出目录存在
    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            print(f"已创建输出目录: {output_dir}")
        except Exception as e:
            print(f"创建输出目录 {output_dir} 时出错: {str(e)}")
            return False
    
    # 查找所有.def文件
    def_files = glob.glob(os.path.join(input_dir, "*.def"))
    
    if not def_files:
        print(f"警告: 在目录 {input_dir} 中未找到.def文件")
        return False
    
    print(f"在目录 {input_dir} 中找到 {len(def_files)} 个.def文件")
    
    # 转换统计
    total = len(def_files)
    successful = 0
    failed = 0
    
    # 处理每个文件
    for i, def_file in enumerate(def_files, 1):
        print(f"\n处理 {i}/{total}: {os.path.basename(def_file)}")
        
        # 构建输出文件路径
        base_name = os.path.splitext(os.path.basename(def_file))[0]
        output_file = os.path.join(output_dir, f"{base_name}.json")
        
        # 转换文件
        if convert_single_file(def_file, output_file):
            successful += 1
        else:
            failed += 1
    
    # 输出统计结果
    print_separator()
    print(f"批处理完成：")
    print(f"总计文件: {total}")
    print(f"成功转换: {successful}")
    print(f"转换失败: {failed}")
    
    return successful > 0

def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="RASPA2到RASPA3分子定义文件转换器")
    
    # 添加目录模式参数
    parser.add_argument("-d", "--dir", action="store_true", 
                      help="启用目录模式，处理指定目录中的所有.def文件")
    
    # 输入文件或目录
    parser.add_argument("input", help="输入文件或目录")
    
    # 输出文件或目录（可选）
    parser.add_argument("output", nargs="?", default=None, 
                      help="输出文件或目录（可选）")
    
    # 显示详细信息
    parser.add_argument("-v", "--verbose", action="store_true", 
                      help="显示详细的调试信息")
    
    args = parser.parse_args()
    
    # 是否启用调试模式
    global DEBUG
    if args.verbose:
        DEBUG = True
        print("已启用详细输出模式")
    
    # 显示开始信息
    print("=" * 60)
    print("RASPA2到RASPA3分子定义转换器")
    print("=" * 60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 根据模式处理文件
    success = False
    if args.dir:
        # 目录模式
        print(f"模式: 批量处理目录")
        input_dir = args.input
        output_dir = args.output
        success = process_directory(input_dir, output_dir)
    else:
        # 单文件模式
        print(f"模式: 单文件处理")
        input_file = args.input
        output_file = args.output
        success = convert_single_file(input_file, output_file)
    
    # 显示结束信息
    print_separator()
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 返回状态码
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main()) 