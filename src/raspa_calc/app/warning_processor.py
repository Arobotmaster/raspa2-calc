#!/usr/bin/env python3
# warning_processor.py - 正确的警告处理模块

import os
import sys
import pandas as pd
import shutil
import subprocess
from typing import List, Dict, Tuple, Set
import re

from raspa_calc.runtime import config as common_config

class WarningProcessor:
    def __init__(self):
        self.current_dir = os.getcwd()
        
        # 固定的警告任务设置
        self.output_dir = 'warning_tasks'
        self.warning_csv_file = 'warning_tasks.csv'
        self.framework_column = 'Framework Name'
        

    def find_csv_files(self) -> List[str]:
        """查找当前目录中的CSV文件"""
        csv_files = []
        for file in os.listdir(self.current_dir):
            if file.endswith('.csv') and not file.startswith('warning_'):
                csv_files.append(file)
        return csv_files
    
    def select_csv_file(self) -> str:
        """让用户选择要处理的CSV文件"""
        csv_files = self.find_csv_files()
        
        if not csv_files:
            print("❌ 当前目录中未找到CSV文件")
            print("请确保您在包含计算结果CSV文件的目录中运行此工具")
            sys.exit(1)
        
        if len(csv_files) == 1:
            selected_file = csv_files[0]
            print(f"📁 自动选择CSV文件: {selected_file}")
            return selected_file
        
        print("📁 发现多个CSV文件:")
        for i, file in enumerate(csv_files, 1):
            print(f"  {i}. {file}")
        
        while True:
            try:
                choice = input(f"请选择要处理的CSV文件 (1-{len(csv_files)}): ").strip()
                index = int(choice) - 1
                if 0 <= index < len(csv_files):
                    return csv_files[index]
                else:
                    print(f"请输入1到{len(csv_files)}之间的数字")
            except ValueError:
                print("请输入有效的数字")
            except KeyboardInterrupt:
                print("\n用户取消操作")
                sys.exit(130)
                
    def select_processing_mode(self):
        """选择处理模式（第1步）"""
        print("\n🎯 请选择警告处理模式:")
        print("1. 提取警告数据 - 从原始CSV中提取包含警告的任务")
        print("2. 替换CSV数据 - 用重新计算的结果替换原始CSV中的警告数据")
        print()
        
        while True:
            try:
                choice = input("请选择处理模式 (1-2): ").strip()
                if choice == '1':
                    return 'extract'
                elif choice == '2':
                    return 'replace'
                else:
                    print("请输入1或2")
            except KeyboardInterrupt:
                print("\n用户取消操作")
                sys.exit(130)
                
    def extract_warning_types(self, warning_str: str) -> List[str]:
        """从警告字符串中动态提取所有警告类型"""
        warning_types = []
        warning_str = str(warning_str).strip()
        
        # 如果警告字符串为空或无效，返回空列表
        if not warning_str or warning_str.lower() in ['nan', 'none', '']:
            return warning_types
        
        # 处理状态标记类型的警告
        status_warnings = ['not_started', 'running', 'failed', 'no_output']
        for status in status_warnings:
            if status in warning_str.lower():
                warning_types.append(status.upper())
        
        # 处理传统的WARNING格式警告
        # 按行或分号分割警告信息
        separators = ['\n', ';', ',']
        warning_parts = [warning_str]
        
        for sep in separators:
            new_parts = []
            for part in warning_parts:
                new_parts.extend(part.split(sep))
            warning_parts = new_parts
        
        for part in warning_parts:
            part = part.strip()
            if not part:
                continue
                
            # 处理WARNING:格式的警告
            if part.upper().startswith('WARNING'):
                if ':' in part:
                    warning_content = part.split(':', 1)[1].strip()
                else:
                    warning_content = part.replace('WARNING', '').strip()
                
                if warning_content and len(warning_content) > 3:
                    warning_content = ' '.join(warning_content.split()).upper()
                    warning_types.append(warning_content)
            
            # 处理其他非状态标记的警告内容
            elif part.lower() not in status_warnings:
                # 过滤掉过短或无意义的内容
                if len(part) > 3 and not part.isdigit():
                    cleaned_part = ' '.join(part.split()).upper()
                    # 排除已知的状态标记
                    if cleaned_part.lower() not in [s.lower() for s in status_warnings]:
                        warning_types.append(cleaned_part)
        
        # 去重并返回
        unique_warnings = []
        for warning in warning_types:
            if warning not in unique_warnings:
                unique_warnings.append(warning)
        
        return unique_warnings
        
    def select_warning_types_to_process(self, warning_df: pd.DataFrame) -> Set[str]:
        """让用户选择需要处理的警告类型"""
        print("\n📊 检测到的警告类型:")
        
        # 统计所有警告类型
        all_warnings = {}
        for warnings in warning_df['Warnings']:
            warning_str = str(warnings)
            warning_types = self.extract_warning_types(warning_str)
            for warning_type in warning_types:
                all_warnings[warning_type] = all_warnings.get(warning_type, 0) + 1
        
        if not all_warnings:
            print("⚠️ 未检测到任何有效的警告类型")
            print("📝 将处理所有包含Warnings信息的任务")
            return set(['ALL_WARNINGS'])  # 返回特殊标识
        
        # 显示警告类型列表
        warning_list = list(all_warnings.items())
        warning_list.sort(key=lambda x: x[1], reverse=True)  # 按数量排序
        
        for i, (warning_type, count) in enumerate(warning_list, 1):
            # 截断过长的警告内容以便显示
            display_warning = warning_type[:80] + '...' if len(warning_type) > 80 else warning_type
            print(f"  {i}. {display_warning}: {count} 个任务")
        
        print("\n📝 选择需要处理的警告类型:")
        print("请输入需要处理的警告类型编号，用空格或逗号分隔")
        print("例如: 1 3 5 或 1,3,5")
        print("输入 'all' 处理所有警告类型")
        print("输入 'auto' 仅处理可自动修复的警告类型")
        
        while True:
            try:
                choice = input("\n您的选择: ").strip()
                
                if choice.lower() == 'all':
                    return set(all_warnings.keys())
                elif choice.lower() == 'auto':
                    # 返回可自动修复的警告类型标识
                    return set(['AUTO_FIX'])
                else:
                    # 解析用户输入的编号
                    selected_indices = []
                    if ',' in choice:
                        parts = choice.split(',')
                    else:
                        parts = choice.split()
                    
                    for part in parts:
                        part = part.strip()
                        if part.isdigit():
                            index = int(part) - 1
                            if 0 <= index < len(warning_list):
                                selected_indices.append(index)
                            else:
                                print(f"无效编号: {part}")
                                raise ValueError()
                        else:
                            print(f"无效输入: {part}")
                            raise ValueError()
                    
                    if selected_indices:
                        selected_warnings = {warning_list[i][0] for i in selected_indices}
                        return selected_warnings
                    else:
                        print("请至少选择一个警告类型")
                        
            except ValueError:
                print("无效输入，请重新输入")
            except KeyboardInterrupt:
                print("\n用户取消操作")
                sys.exit(130)
                
    def analyze_warnings(self, csv_file: str) -> pd.DataFrame:
        """分析CSV文件中的警告信息"""
        print(f"\n🔍 分析警告信息: {csv_file}")
        
        try:
            # 读取CSV文件，处理BOM编码
            df = pd.read_csv(csv_file, encoding='utf-8-sig')
            print(f"✅ 成功加载CSV文件: {len(df)} 行数据")
        except Exception as e:
            print(f"❌ 读取CSV文件失败: {e}")
            sys.exit(1)
        
        # 检查是否有Warnings列
        if 'Warnings' not in df.columns:
            print("❌ CSV文件中未找到'Warnings'列")
            print("请确保使用的是包含警告信息的数据提取结果")
            sys.exit(1)
        
        # 筛选有警告的任务
        warning_mask = df['Warnings'].notna() & (df['Warnings'] != '') & (df['Warnings'] != 'nan')
        warning_df = df[warning_mask].copy()
        
        if warning_df.empty:
            print("✅ 恭喜！没有发现任何警告任务")
            print("所有计算任务都正常完成，无需进一步处理")
            return pd.DataFrame()
        
        print(f"⚠️ 发现 {len(warning_df)} 个有警告的任务")
        
        # 让用户选择需要处理的警告类型
        selected_warning_types = self.select_warning_types_to_process(warning_df)
        
        if not selected_warning_types:
            print("未选择任何警告类型，结束处理")
            return pd.DataFrame()
        
        # 处理特殊标识符
        if 'ALL_WARNINGS' in selected_warning_types:
            print(f"\n✅ 将处理所有包含Warnings信息的任务: {len(warning_df)} 个")
            return warning_df
            
        if 'AUTO_FIX' in selected_warning_types:
            print(f"\n🔧 自动修复模式：处理可自动修复的警告类型")
            # 定义可自动修复的警告类型模式
            auto_fix_patterns = [
                "THE SYSTEM HAS A NET CHARGE",
                "INAPPROPRIATE NUMBER OF UNIT CELLS",
                "ENERGY DRIFT",
                "THERE ARE ATOM-PAIRS WITH NO VDW INTERACTION",
                "GRID FORCE INTERPOLATION PROBABLY NOT ACCURATE ENOUGH",
                "REINSERTION MOVE USED ON CHARGED IONS"
            ]
            # 筛选包含可自动修复警告的任务
            filtered_warning_df = []
            for _, row in warning_df.iterrows():
                warning_str = str(row['Warnings']).upper()
                if any(pattern in warning_str for pattern in auto_fix_patterns):
                    filtered_warning_df.append(row)
            
            filtered_warning_df = pd.DataFrame(filtered_warning_df)
            if filtered_warning_df.empty:
                print("未找到可自动修复的警告任务")
                return pd.DataFrame()
            print(f"✅ 找到可自动修复的警告任务: {len(filtered_warning_df)} 个")
            return filtered_warning_df
        
        print(f"\n✅ 已选择 {len(selected_warning_types)} 种警告类型进行处理:")
        for warning_type in selected_warning_types:
            print(f"  • {warning_type[:80]}{'...' if len(warning_type) > 80 else ''}")
        
        # 筛选包含所选警告类型的任务
        filtered_warning_df = []
        for _, row in warning_df.iterrows():
            warning_str = str(row['Warnings'])
            row_warning_types = self.extract_warning_types(warning_str)
            # 检查是否包含任何所选的警告类型
            if any(wt in selected_warning_types for wt in row_warning_types):
                filtered_warning_df.append(row)
        
        filtered_warning_df = pd.DataFrame(filtered_warning_df)
        
        if filtered_warning_df.empty:
            print("未找到包含所选警告类型的任务")
            return pd.DataFrame()
        
        print(f"\n✅ 筛选后需要处理的警告任务: {len(filtered_warning_df)} 个")
        
        return filtered_warning_df
    
    def generate_warning_csv(self, warning_df: pd.DataFrame):
        """生成警告任务CSV文件（第3步）"""
        print(f"\n📝 生成警告任务CSV文件...")
        
        # 确保输出目录存在
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            print(f"✅ 创建输出目录: {self.output_dir}")
            
        # 重新排列索引，从1开始
        warning_df_reset = warning_df.reset_index(drop=True)
        warning_df_reset.index += 1
        
        # 保存警告任务CSV
        csv_path = os.path.join(self.output_dir, self.warning_csv_file)
        warning_df_reset.to_csv(csv_path, index=True, index_label='Warning_Task_ID')
        print(f"✅ 警告任务CSV已生成: {csv_path}")
        
        return csv_path
        
    def show_usage_guide(self):
        """显示使用指导信息"""
        print(f"\n📋 警告处理已完成，手动配置指导：")
        print("=" * 60)
        print("📄 警告任务已生成:")
        print(f"   • CSV文件: {self.output_dir}/{self.warning_csv_file}")
        print(f"   • 输出目录: {self.output_dir}")
        print(f"   • 框架列名: {self.framework_column}")
        print()
        print("🛠️ 需要修改config.yaml中的以下参数:")
        print("   calculation:")
        print(f"     csv_file_path: \"{os.path.abspath(os.path.join(self.output_dir, self.warning_csv_file))}\"")
        print(f"     output_directory: \"{self.output_dir}\"")
        print(f"     framework_column: \"{self.framework_column}\"")
        print()
        print("🚀 修改完成后的操作步骤:")
        print("   1. 保存config.yaml文件")
        print("   2. 运行: python -m raspa_calc --no-check")
        print("   3. 选择选项2（高通量计算模式）")
        print("   4. 系统将使用警告任务进行计算")
        print()
        print("💡 提示: 计算完成后，记得恢复原有的config.yaml设置")
        print("=" * 60)
        
    def replace_csv_data(self):
        """替换CSV数据模式 - 用重新计算的结果替换原始CSV中的数据"""
        print("\n🔄 CSV数据替换模式")
        print("该模式将用重新计算的结果替换原始CSV文件中对应的数据行")
        print()
        
        # 选择原始CSV文件
        print("步骤1: 选择原始CSV文件")
        original_csv_file = self.select_csv_file()
        
        # 选择重新计算的CSV文件
        print("\n步骤2: 选择重新计算的CSV文件")
        print("请选择包含重新计算结果的CSV文件:")
        recalculated_csv_file = self.select_csv_file()
        
        # 让用户选择匹配列
        framework_column = self.select_matching_columns(original_csv_file, recalculated_csv_file)
        if not framework_column:
            print("\n❌ 用户取消操作或无有效匹配列")
            return
        
        # 执行替换操作
        self.perform_csv_replacement(original_csv_file, recalculated_csv_file, framework_column)
        
    def select_matching_columns(self, original_csv_file, recalculated_csv_file):
        """让用户选择用于匹配的列名"""
        print(f"\n🔍 步骤3: 选择匹配列")
        print("为了确保数据准确匹配，请选择用于匹配的列名")
        print()
        
        try:
            # 读取两个CSV文件的列名
            original_df = pd.read_csv(original_csv_file, encoding='utf-8-sig', nrows=0)  # 只读取列名
            recalculated_df = pd.read_csv(recalculated_csv_file, encoding='utf-8-sig', nrows=0)
            
            # 找到共同的列名
            common_columns = list(set(original_df.columns) & set(recalculated_df.columns))
            
            if not common_columns:
                print("❌ 两个CSV文件没有共同的列名，无法进行匹配")
                return None
            
            # 按字母顺序排列，但将常见的框架列名放在前面
            priority_columns = ['coreid', 'refcode', 'framework', 'Framework Name', 'name', 'structure']
            sorted_columns = []
            
            # 先添加优先列
            for col in priority_columns:
                if col in common_columns:
                    sorted_columns.append(col)
                    common_columns.remove(col)
            
            # 再添加其他列（按字母顺序）
            sorted_columns.extend(sorted(common_columns))
            
            print(f"📄 原始CSV列名: {list(original_df.columns)}")
            print(f"📄 重计算CSV列名: {list(recalculated_df.columns)}")
            print(f"✅ 共同列名: {len(sorted_columns)} 个")
            print()
            
            print("🎯 请选择用于匹配的列名:")
            for i, col in enumerate(sorted_columns, 1):
                print(f"  {i}. {col}")
            print()
            
            while True:
                try:
                    choice = input(f"请输入列号 (1-{len(sorted_columns)}): ").strip()
                    if choice.isdigit():
                        index = int(choice) - 1
                        if 0 <= index < len(sorted_columns):
                            selected_column = sorted_columns[index]
                            print(f"✅ 已选择匹配列: {selected_column}")
                            
                            # 显示该列的数据样本
                            self.show_column_samples(original_csv_file, recalculated_csv_file, selected_column)
                            
                            # 让用户确认
                            confirm = input("\n确认使用该列进行匹配吗? (y/n): ").strip().lower()
                            if confirm in ['y', 'yes', '是']:
                                return selected_column
                            else:
                                print("请重新选择...")
                        else:
                            print(f"请输入1到{len(sorted_columns)}之间的数字")
                    else:
                        print("请输入有效的数字")
                except KeyboardInterrupt:
                    print("\n用户取消操作")
                    return None
                    
        except Exception as e:
            print(f"❌ 读取CSV文件列名失败: {e}")
            return None
    
    def show_column_samples(self, original_csv_file, recalculated_csv_file, column_name):
        """显示指定列的数据样本"""
        try:
            print(f"\n🔍 预览列 '{column_name}' 的数据样本:")
            
            # 读取原始数据样本
            original_sample = pd.read_csv(original_csv_file, encoding='utf-8-sig', nrows=5)
            if column_name in original_sample.columns:
                original_values = original_sample[column_name].dropna().head(3).tolist()
                print(f"📄 原始CSV中的 '{column_name}': {original_values}")
            
            # 读取重计算数据样本
            recalc_sample = pd.read_csv(recalculated_csv_file, encoding='utf-8-sig', nrows=5)
            if column_name in recalc_sample.columns:
                recalc_values = recalc_sample[column_name].dropna().head(3).tolist()
                print(f"📄 重计算CSV中的 '{column_name}': {recalc_values}")
                
        except Exception as e:
            print(f"⚠️ 无法读取数据样本: {e}")
    
    def get_framework_column_from_config(self):
        """从配置文件获取framework_column设置"""
        try:
            config, _ = common_config.load_config(
                search_mode="upward",
                start_dir=self.current_dir,
            )
            if config:
                return config.get('calculation', {}).get('framework_column', 'coreid')
        except Exception as e:
            print(f"读取配置文件失败: {e}")
        return None
        
    def perform_csv_replacement(self, original_csv_file, recalculated_csv_file, framework_column):
        """执行CSV数据替换"""
        print(f"\n🔄 正在执行数据替换...")
        print(f"原始CSV: {original_csv_file}")
        print(f"重计算CSV: {recalculated_csv_file}")
        print(f"匹配列名: {framework_column}")
        print()
        
        try:
            # 读取原始数据
            original_df = pd.read_csv(original_csv_file, encoding='utf-8-sig')
            print(f"✅ 原始CSV加载成功: {len(original_df)} 行数据")
            
            # 读取重新计算数据
            recalculated_df = pd.read_csv(recalculated_csv_file, encoding='utf-8-sig')
            print(f"✅ 重计算CSV加载成功: {len(recalculated_df)} 行数据")
            
            # 检查匹配列是否存在
            if framework_column not in original_df.columns:
                print(f"❌ 原始CSV中未找到列: {framework_column}")
                print(f"可用列名: {list(original_df.columns)}")
                return
                
            if framework_column not in recalculated_df.columns:
                print(f"❌ 重计算CSV中未找到列: {framework_column}")
                print(f"可用列名: {list(recalculated_df.columns)}")
                return
            
            # 执行替换
            replacement_count = 0
            updated_original_df = original_df.copy()
            
            print(f"正在根据 {framework_column} 列进行数据匹配和替换...")
            
            for idx, recalc_row in recalculated_df.iterrows():
                framework_value = recalc_row[framework_column]
                
                # 在原始数据中查找匹配行
                matching_rows = original_df[original_df[framework_column] == framework_value]
                
                if len(matching_rows) == 1:
                    # 找到唯一匹配行，执行替换
                    original_idx = matching_rows.index[0]
                    
                    # 只替换存在于两个CSV文件中的列
                    common_columns = set(original_df.columns) & set(recalculated_df.columns)
                    common_columns.discard(framework_column)  # 不替换匹配列本身
                    
                    for col in common_columns:
                        updated_original_df.loc[original_idx, col] = recalc_row[col]
                    
                    replacement_count += 1
                    print(f"✅ 替换第 {replacement_count} 行: {framework_value}")
                    
                elif len(matching_rows) > 1:
                    print(f"⚠️ 警告: 找到多个匹配行为 {framework_value}，跳过")
                else:
                    print(f"⚠️ 警告: 未找到匹配行为 {framework_value}")
            
            # 保存更新后的数据
            output_file = self.save_updated_csv(updated_original_df, original_csv_file)
            
            print(f"\n✅ 数据替换完成!")
            print(f"✅ 成功替换: {replacement_count} 行数据")
            print(f"✅ 输出文件: {output_file}")
            
        except Exception as e:
            print(f"❌ 数据替换失败: {e}")
            import traceback
            traceback.print_exc()
    
    def save_updated_csv(self, updated_df, original_csv_file):
        """保存更新后的CSV文件"""
        # 生成输出文件名
        base_name = os.path.splitext(os.path.basename(original_csv_file))[0]
        output_file = f"{base_name}_updated.csv"
        
        # 如果输出目录不存在，创建它
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        output_path = os.path.join(self.output_dir, output_file)
        
        # 保存文件
        updated_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        return output_path
        

    def process_warnings(self):
        """警告处理主流程（增强CSV替换功能）"""
        print("🎯 启动警告处理流程...")
        print("支持两种模式：")
        print("1. 提取警告数据 - 传统模式：分析→选择→生成CSV→显示指导")
        print("2. 替换CSV数据 - 新模式：用重新计算的结果替换原始数据")
        print("=" * 50)
        
        # 步骤1: 选择处理模式
        mode = self.select_processing_mode()
        
        if mode == 'extract':
            # 传统模式：提取警告数据
            self.process_extract_mode()
        elif mode == 'replace':
            # 新模式：CSV数据替换
            self.replace_csv_data()
    
    def process_extract_mode(self):
        """传统的提取警告数据模式"""
        print("\n🔍 提取警告数据模式")
        print("传统流程：")
        print("1. 分析original.csv中的警告")
        print("2. 用户选择警告类型") 
        print("3. 生成warning_tasks.csv")
        print("4. 显示手动配置指导")
        print("=" * 50)
        
        # 步骤1-2：选择并分析CSV文件
        csv_file = self.select_csv_file()
        warning_df = self.analyze_warnings(csv_file)
        
        if warning_df.empty:
            return
        
        # 步骤3：生成警告任务CSV文件
        warning_csv_path = self.generate_warning_csv(warning_df)
        
        # 步骤4：显示手动配置指导
        self.show_usage_guide()
        
        print("\n✅ 警告处理流程完成！")
        print(f"📋 处理了 {len(warning_df)} 个警告任务")
        print(f"📁 输出目录: {self.output_dir}")
        print(f"📄 CSV文件: {warning_csv_path}")

def main():
    """主函数"""
    processor = WarningProcessor()
    processor.process_warnings()

if __name__ == "__main__":
    main()
