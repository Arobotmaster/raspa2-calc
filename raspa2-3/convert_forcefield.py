#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RASPA2到RASPA3力场文件转换器

此脚本用于将RASPA2格式的力场文件转换为RASPA3的JSON格式。
它会读取pseudo_atoms.def和force_field_mixing_rules.def文件，
并生成符合RASPA3格式要求的force_field.json文件。

用法:
    单文件模式:
        python convert_forcefield.py [pseudo_atoms_file] [force_field_file] [output_json_file]
    
    批量处理模式:
        python convert_forcefield.py -d <input_directory> [output_directory]
        python convert_forcefield.py --dir <input_directory> [output_directory]

参数:
    pseudo_atoms_file    - RASPA2伪原子定义文件路径 (默认: pseudo_atoms.def)
    force_field_file     - RASPA2力场混合规则文件路径 (默认: force_field_mixing_rules.def)
    output_json_file     - 输出的RASPA3 JSON力场文件路径 (默认: force_field_raspa3.json)
    
    -d, --dir            - 启用目录模式，处理指定目录中的所有.def文件对
    input_directory      - 包含.def文件的输入目录
    output_directory     - 输出.json文件的目录 (默认: 与输入目录相同)

示例:
    python convert_forcefield.py
    python convert_forcefield.py my_pseudo_atoms.def my_force_field.def my_output.json
    python convert_forcefield.py -d ./forcefield_files
    python convert_forcefield.py --dir ./forcefield_files ./output
"""

import json
import re
import os
import sys
import time
import glob
import argparse
from datetime import datetime

def print_separator():
    """打印分隔行"""
    print("-" * 60)

def read_pseudo_atoms(filename):
    """读取pseudo_atoms.def文件并提取参数"""
    print_separator()
    print(f"读取伪原子文件: {filename}")
    
    pseudo_atoms = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"读取文件 {filename} 时出错: {str(e)}")
        return []
    
    print(f"文件共 {len(lines)} 行")
    
    # 跳过注释行，找到数量行
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('#')):
        i += 1
    
    # 确保找到了有效的数量行
    if i >= len(lines):
        print(f"在文件 {filename} 中未找到有效的原子数量行")
        return []
    
    try:
        num_atoms = int(lines[i].strip().split()[0])
        print(f"检测到 {num_atoms} 个伪原子定义")
    except (ValueError, IndexError):
        print(f"无法解析原子数量行: {lines[i]}")
        # 继续处理，尝试读取所有行
    
    # 跳过数量行和标题行
    i += 2
    
    # 开始读取原子数据
    print("开始解析伪原子数据...")
    processed = 0
    start_time = time.time()
    
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        
        if not line or line.startswith('#'):
            continue
            
        parts = line.split()
        if len(parts) < 8:  # 确保有足够的列
            continue
        
        try:
            atom_name = parts[0]
            print_to_output = parts[1].lower() == "yes"
            print_as = parts[2]
            element = parts[3]
            # oxidation = parts[4]  # RASPA3不使用
            mass = float(parts[5])
            charge = float(parts[6])
            
            # 判断是否为框架原子（根据名称是否有后缀）
            # 如果名称中包含下划线，则认为有后缀，不是框架原子
            is_framework = "_" not in atom_name
            
            # 创建RASPA3格式的PseudoAtom对象，只保留与force_field.json相同的字段
            atom = {
                "name": atom_name,
                "framework": is_framework,  # 根据名称是否有后缀来设置
                "print_to_output": print_to_output,
                "element": element,
                "print_as": print_as,
                "mass": mass,
                "charge": charge
            }
            
            pseudo_atoms.append(atom)
            processed += 1
            
            # 每处理10个原子显示一次进度
            if processed % 10 == 0:
                print(f"已处理 {processed} 个伪原子...")
                
        except Exception as e:
            print(f"处理行 {line} 时出错: {str(e)}")
            continue
    
    elapsed_time = time.time() - start_time
    print(f"成功解析 {len(pseudo_atoms)} 个伪原子，耗时 {elapsed_time:.2f} 秒")
    return pseudo_atoms

def read_force_field_mixing_rules(filename):
    """读取force_field_mixing_rules.def文件并提取参数"""
    print_separator()
    print(f"读取力场混合规则文件: {filename}")
    
    self_interactions = []
    mixing_rule = "Lorentz-Berthelot"  # 默认值
    truncation_method = "truncated"    # 默认值
    tail_corrections = False           # 默认值
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"读取文件 {filename} 时出错: {str(e)}")
        return [], mixing_rule, truncation_method, tail_corrections
    
    print(f"文件共 {len(lines)} 行")
    print("开始解析力场参数...")
    
    # 寻找混合规则、截断方法和尾部校正
    i = 0
    num_interactions = 0
    processed = 0
    start_time = time.time()
    
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        
        if not line or line.startswith('#'):
            continue
        
        # 检查截断方法
        if line.lower() in ["truncated", "shifted"]:
            truncation_method = line.lower()
            print(f"截断方法: {truncation_method}")
            continue
            
        # 检查尾部校正
        if line.lower() in ["yes", "no"]:
            tail_corrections = (line.lower() == "yes")
            print(f"尾部校正: {tail_corrections}")
            continue
            
        # 检查是否是定义的相互作用数量行
        if "number of defined interactions" in line.lower():
            try:
                num_interactions = int(line.split()[0])
                print(f"定义的相互作用数量: {num_interactions}")
            except (ValueError, IndexError):
                print(f"无法解析相互作用数量: {line}")
            continue
            
        # 检查混合规则
        if "lorentz-berthelot" in line.lower():
            mixing_rule = "Lorentz-Berthelot"
            print(f"混合规则: {mixing_rule}")
            continue
        
        # 尝试读取相互作用参数
        # 首先分离注释
        comment = ""
        if "//" in line:
            parts = line.split("//", 1)
            line = parts[0].strip()
            comment = parts[1].strip()
        
        parts = line.split()
        if len(parts) >= 2:  # 确保至少有name和type
            try:
                # 提取参数
                name = parts[0]
                interaction_type = parts[1].lower()
                
                # 处理Lennard-Jones类型的不同写法
                if interaction_type in ["lennard-jones", "lennard_jones", "lennard", "lj"]:
                    interaction_type = "lennard-jones"
                
                # 创建RASPA3格式的SelfInteraction对象
                interaction = {
                    "name": name,
                    "type": interaction_type,
                    "parameters": [],  # 默认为空列表
                    "source": comment if comment else "Converted from RASPA2"
                }
                
                # 如果不是none类型，则提取epsilon和sigma参数
                if interaction_type != "none":
                    if len(parts) >= 4:
                        try:
                            epsilon = float(parts[2])
                            sigma = float(parts[3])
                            interaction["parameters"] = [epsilon, sigma]
                        except ValueError:
                            print(f"警告: 行 {line} 中的epsilon或sigma参数无效，跳过")
                            continue
                    else:
                        print(f"警告: 行 {line} 缺少epsilon和sigma参数，跳过")
                        continue
                
                self_interactions.append(interaction)
                processed += 1
                
                # 每处理10个相互作用显示一次进度
                if processed % 10 == 0:
                    print(f"已处理 {processed} 个相互作用...")
                    
            except Exception as e:
                print(f"处理行 {line} 时出错: {str(e)}")
                continue
    
    elapsed_time = time.time() - start_time
    print(f"成功解析 {len(self_interactions)} 个自相互作用，耗时 {elapsed_time:.2f} 秒")
    return self_interactions, mixing_rule, truncation_method, tail_corrections

def create_forcefield_json(pseudo_atoms, self_interactions, mixing_rule, truncation_method, tail_corrections, output_file):
    """创建RASPA3格式的力场JSON文件"""
    print_separator()
    print(f"创建RASPA3 JSON力场文件: {output_file}")
    
    # 检查是否有数据
    if not pseudo_atoms:
        print("警告: 没有伪原子数据")
    if not self_interactions:
        print("警告: 没有自相互作用数据")
        
    # 构建力场对象
    force_field = {
        "PseudoAtoms": pseudo_atoms,
        "SelfInteractions": self_interactions,
        "MixingRule": mixing_rule,
        "TruncationMethod": truncation_method,
        "TailCorrections": tail_corrections
    }
    
    # 统计信息
    print(f"PseudoAtoms: {len(pseudo_atoms)} 项")
    print(f"SelfInteractions: {len(self_interactions)} 项")
    print(f"MixingRule: {mixing_rule}")
    print(f"TruncationMethod: {truncation_method}")
    print(f"TailCorrections: {tail_corrections}")
    
    # 将字典写入JSON文件，使用自定义格式
    try:
        # 确保输出目录存在
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"已创建输出目录: {output_dir}")
            
        # 自定义JSON格式输出，每条记录单行
        json_content = "{\n"

        # PseudoAtoms部分
        json_content += '  "PseudoAtoms" :\n  [\n'
        for i, atom in enumerate(pseudo_atoms):
            comma = ',' if i < len(pseudo_atoms) - 1 else ''
            fw = str(atom["framework"]).lower()
            pto = str(atom["print_to_output"]).lower()
            json_content += (
                f'    {{"name": "{atom["name"]}", "framework": {fw}, '
                f'"print_to_output": {pto}, "element": "{atom["element"]}", '
                f'"print_as": "{atom["print_as"]}", "mass": {atom["mass"]}, '
                f'"charge": {atom["charge"]}}}{comma}\n'
            )
        json_content += '  ],\n'

        # SelfInteractions部分
        json_content += '  "SelfInteractions" :\n  [\n'
        for i, interaction in enumerate(self_interactions):
            comma = ',' if i < len(self_interactions) - 1 else ''
            if interaction["parameters"]:
                params = f'[{interaction["parameters"][0]}, {interaction["parameters"][1]}]'
            else:
                params = '[]'
            json_content += (
                f'    {{"name": "{interaction["name"]}", "type": "{interaction["type"]}", '
                f'"parameters": {params}, "source": "{interaction["source"]}"}}{comma}\n'
            )
        json_content += '  ],\n'
        
        # 全局参数
        json_content += f'  "MixingRule" : "{mixing_rule}",\n'
        json_content += f'  "TruncationMethod" : "{truncation_method}",\n'
        json_content += f'  "TailCorrections" : {str(tail_corrections).lower()}\n'
        
        json_content += '}\n'
        
        # 写入文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(json_content)
        
        file_size = os.path.getsize(output_file) / 1024  # 转换为KB
        print(f"已成功创建RASPA3力场文件: {output_file} (大小: {file_size:.2f} KB)")
        return True
    except Exception as e:
        print(f"写入JSON文件 {output_file} 时出错: {str(e)}")
        return False

def convert_forcefield(pseudo_atoms_file, force_field_file, output_json_file):
    """转换单个力场文件集"""
    
    # 检查文件是否存在
    if not os.path.exists(pseudo_atoms_file):
        print(f"错误: 文件 {pseudo_atoms_file} 不存在")
        return False
    
    if not os.path.exists(force_field_file):
        print(f"错误: 文件 {force_field_file} 不存在")
        return False
    
    print_separator()
    print(f"处理力场文件: ")
    print(f"伪原子文件: {os.path.abspath(pseudo_atoms_file)}")
    print(f"力场混合规则文件: {os.path.abspath(force_field_file)}")
    print(f"输出JSON文件: {os.path.abspath(output_json_file)}")
    
    # 读取伪原子定义
    pseudo_atoms = read_pseudo_atoms(pseudo_atoms_file)
    
    # 读取力场混合规则
    self_interactions, mixing_rule, truncation_method, tail_corrections = read_force_field_mixing_rules(force_field_file)
    
    # 创建JSON力场文件
    return create_forcefield_json(pseudo_atoms, self_interactions, mixing_rule, truncation_method, tail_corrections, output_json_file)

def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="RASPA2到RASPA3力场文件转换器")
    
    # 输入文件
    parser.add_argument("pseudo_atoms_file", nargs="?", default="pseudo_atoms.def", 
                       help="RASPA2伪原子定义文件路径")
    
    # 输入文件
    parser.add_argument("force_field_file", nargs="?", default="force_field_mixing_rules.def", 
                       help="RASPA2力场混合规则文件路径")
    
    # 输出JSON文件
    parser.add_argument("output_json_file", nargs="?", default="force_field_raspa3.json", 
                       help="输出的RASPA3 JSON力场文件路径")
    
    args = parser.parse_args()
    
    # 显示开始信息
    print("=" * 60)
    print("RASPA2到RASPA3力场文件转换器")
    print("=" * 60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 处理文件
    success = convert_forcefield(args.pseudo_atoms_file, args.force_field_file, args.output_json_file)
    
    # 显示结束信息
    print_separator()
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 返回状态码
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())