#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MOF数据库筛选工具 - 改进版
功能：根据CSV条件筛选数据，并可选复制对应的CIF文件
"""

import pandas as pd
import os
import shutil
from pathlib import Path

class MOFFilterTool:
    """MOF数据筛选工具类"""

    def __init__(self):
        self.df = None
        self.csv_file = None
        self.filtered_df = None
        self.original_count = 0
        self.mode = None  # 'filter' 或 'extract'

    def print_header(self, title):
        """打印标题"""
        print("\n" + "=" * 70)
        print(f"  {title}")
        print("=" * 70)

    def print_section(self, title):
        """打印小标题"""
        print(f"\n▶ {title}")
        print("-" * 70)

    def load_csv(self):
        """加载CSV文件"""
        self.print_section("第二步：选择CSV文件")
        print("说明：选择包含待筛选数据的CSV文件")

        while True:
            csv_file = input("\n请输入CSV文件路径（支持相对路径或绝对路径）: ").strip()

            if not os.path.exists(csv_file):
                print(f"❌ 错误：文件不存在，请检查路径: {csv_file}")
                continue

            # 尝试读取文件
            encoding_list = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin1']
            df = None

            for encoding in encoding_list:
                try:
                    df = pd.read_csv(csv_file, encoding=encoding)
                    print(f"✅ 文件读取成功（编码: {encoding}）")
                    break
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue

            if df is None:
                print(f"❌ 错误：无法读取文件，请尝试其他编码")
                continue

            self.df = df
            self.csv_file = csv_file
            self.original_count = len(df)
            break

        # 显示数据概览
        self.show_data_info()

    def show_data_info(self):
        """显示数据信息"""
        self.print_section("数据概览")
        print(f"文件名: {os.path.basename(self.csv_file)}")
        print(f"数据总行数: {len(self.df)} 行")
        print(f"数据总列数: {len(self.df.columns)} 列")

        print(f"\n可用的列名 (共 {len(self.df.columns)} 列):")
        columns = self.df.columns.tolist()
        for i, col in enumerate(columns, 1):
            print(f"  {i}. {col}")

        # 显示前5行数据预览
        print(f"\n数据预览 (前5行):")
        preview_df = self.df.head().copy()  # 创建副本避免警告
        for col in preview_df.columns:
            preview_df[col] = preview_df[col].astype(str)
        print(preview_df.to_string(max_colwidth=30))

    def extract_by_refcode(self):
        """根据另一个CSV文件的refcode提取数据"""
        self.print_section("第三步：根据refcode提取数据")
        print("说明：提供另一个CSV文件，根据其中的refcode列提取匹配的数据")

        while True:
            reference_file = input("\n请输入参考CSV文件路径（包含refcode列）: ").strip()

            if not os.path.exists(reference_file):
                print(f"❌ 错误：文件不存在，请检查路径: {reference_file}")
                continue

            # 读取参考文件
            encoding_list = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin1']
            ref_df = None

            for encoding in encoding_list:
                try:
                    ref_df = pd.read_csv(reference_file, encoding=encoding)
                    print(f"✅ 参考文件读取成功（编码: {encoding}）")
                    break
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue

            if ref_df is None:
                print(f"❌ 错误：无法读取参考文件")
                continue

            # 检查refcode列
            if 'refcode' not in ref_df.columns:
                print(f"❌ 错误：参考文件中没有'refcode'列")
                print(f"   可用列: {', '.join(ref_df.columns.tolist())}")
                continue

            if 'refcode' not in self.df.columns:
                print(f"❌ 错误：源文件中没有'refcode'列")
                print(f"   可用列: {', '.join(self.df.columns.tolist())}")
                return

            # 提取refcode列表
            refcodes_to_extract = set(ref_df['refcode'].dropna())
            print(f"✅ 从参考文件中提取到 {len(refcodes_to_extract)} 个唯一refcode")

            # 执行匹配
            self.filtered_df = self.df[self.df['refcode'].isin(refcodes_to_extract)].copy()

            # 统计结果
            print(f"\n✅ 提取完成")
            print(f"   参考文件: {os.path.basename(reference_file)}")
            print(f"   参考refcode数量: {len(refcodes_to_extract)}")
            print(f"   匹配成功: {len(self.filtered_df)} 行")
            print(f"   未找到: {len(refcodes_to_extract) - len(self.filtered_df)} 个")
            print(f"   匹配率: {len(self.filtered_df)/len(refcodes_to_extract)*100:.1f}%")
            break

    def setup_filters(self):
        """设置筛选条件"""
        self.print_section("第三步：设置筛选条件")
        print("说明：可以设置多个条件，数据必须同时满足所有条件才会被保留")
        print("      直接按回车可以结束条件设置")

        self.filtered_df = self.df.copy()  # 创建副本避免警告
        filter_count = 0

        while True:
            print(f"\n--- 条件 {filter_count + 1} ---")

            # 选择要筛选的列
            column = input("请输入要筛选的列名 (或按Enter结束条件设置): ").strip()
            if not column:
                break

            if column not in self.df.columns:
                print(f"❌ 错误：列'{column}'不存在")
                print(f"   可用列: {', '.join(self.df.columns.tolist()[:5])}")
                continue

            # 确定列的数据类型
            sample_values = self.df[column].dropna().head()
            is_numeric = pd.api.types.is_numeric_dtype(self.df[column])

            print(f"✓ 已选择列: {column}")
            if is_numeric:
                print(f"  (数值类型) 样本值: {sample_values.tolist()}")
            else:
                print(f"  (文本类型) 样本值: {sample_values.tolist()}")

            # 选择筛选方式
            self.apply_single_filter(column, is_numeric)
            filter_count += 1
            print(f"✅ 已添加第 {filter_count} 个条件，当前数据行数: {len(self.filtered_df)}")

        print(f"\n✅ 筛选条件设置完成")
        print(f"   原始数据: {self.original_count} 行")
        print(f"   筛选后: {len(self.filtered_df)} 行")
        print(f"   保留比例: {len(self.filtered_df)/self.original_count*100:.1f}%")

    def apply_single_filter(self, column, is_numeric):
        """应用单个筛选条件"""
        if is_numeric:
            self.apply_numeric_filter(column)
        else:
            self.apply_text_filter(column)

    def apply_numeric_filter(self, column):
        """应用数值筛选"""
        print("\n数值筛选方式:")
        print("  1. 大于某值 (>)")
        print("  2. 小于某值 (<)")
        print("  3. 等于某值 (=)")
        print("  4. 在某个范围内 (between)")

        choice = input("请选择筛选方式 (1-4): ").strip()

        if choice == '1':
            try:
                value = float(input("请输入数值: "))
                self.filtered_df = self.filtered_df[self.filtered_df[column] > value].copy()
                print(f"✓ 筛选: {column} > {value}")
            except ValueError:
                print("❌ 错误：请输入有效的数字")

        elif choice == '2':
            try:
                value = float(input("请输入数值: "))
                self.filtered_df = self.filtered_df[self.filtered_df[column] < value].copy()
                print(f"✓ 筛选: {column} < {value}")
            except ValueError:
                print("❌ 错误：请输入有效的数字")

        elif choice == '3':
            try:
                value = float(input("请输入数值: "))
                self.filtered_df = self.filtered_df[self.filtered_df[column] == value].copy()
                print(f"✓ 筛选: {column} = {value}")
            except ValueError:
                print("❌ 错误：请输入有效的数字")

        elif choice == '4':
            try:
                min_val = float(input("请输入最小值: "))
                max_val = float(input("请输入最大值: "))
                self.filtered_df = self.filtered_df[
                    (self.filtered_df[column] >= min_val) &
                    (self.filtered_df[column] <= max_val)
                ].copy()
                print(f"✓ 筛选: {min_val} <= {column} <= {max_val}")
            except ValueError:
                print("❌ 错误：请输入有效的数字")
        else:
            print("❌ 错误：请输入有效的选择 (1-4)")

    def apply_text_filter(self, column):
        """应用文本筛选"""
        print("\n文本筛选方式:")
        print("  1. 等于某值")
        print("  2. 包含某值")
        print("  3. 以...开头")
        print("  4. 以...结尾")
        print("  5. 在列表中")

        choice = input("请选择筛选方式 (1-5): ").strip()

        if choice == '1':
            value = input("请输入文本: ").strip()
            self.filtered_df = self.filtered_df[self.filtered_df[column].astype(str) == value].copy()
            print(f"✓ 筛选: {column} = '{value}'")

        elif choice == '2':
            value = input("请输入文本: ").strip()
            self.filtered_df = self.filtered_df[
                self.filtered_df[column].astype(str).str.contains(value, case=False, na=False)
            ].copy()
            print(f"✓ 筛选: {column} 包含 '{value}'")

        elif choice == '3':
            value = input("请输入文本: ").strip()
            self.filtered_df = self.filtered_df[
                self.filtered_df[column].astype(str).str.startswith(value, na=False)
            ].copy()
            print(f"✓ 筛选: {column} 以 '{value}' 开头")

        elif choice == '4':
            value = input("请输入文本: ").strip()
            self.filtered_df = self.filtered_df[
                self.filtered_df[column].astype(str).str.endswith(value, na=False)
            ].copy()
            print(f"✓ 筛选: {column} 以 '{value}' 结尾")

        elif choice == '5':
            print("请输入多个值，用逗号分隔 (例: value1,value2,value3)")
            values = [v.strip() for v in input("请输入文本列表: ").split(',')]
            self.filtered_df = self.filtered_df[
                self.filtered_df[column].astype(str).isin(values)
            ].copy()
            print(f"✓ 筛选: {column} 在 {values}")

        else:
            print("❌ 错误：请输入有效的选择 (1-5)")

    def save_csv_result(self):
        """保存筛选后的CSV"""
        self.print_section("第四步：保存筛选结果")
        print("说明：将筛选后的数据保存为新的CSV文件")

        output_file = input("\n请输入输出CSV文件名 (包含.csv后缀): ").strip()
        if not output_file.endswith('.csv'):
            output_file += '.csv'

        try:
            self.filtered_df.to_csv(output_file, index=False, encoding='utf-8-sig')
            print(f"✅ 文件已保存: {output_file}")
            print(f"   数据行数: {len(self.filtered_df)} 行")
            return output_file
        except Exception as e:
            print(f"❌ 保存失败: {e}")
            return None

    def copy_cif_files(self):
        """复制筛选后的CIF文件"""
        self.print_section("第五步：复制CIF文件")
        print("说明：根据筛选结果复制对应的CIF文件")

        # 选择包含文件名的列
        print(f"\n可用的列: {', '.join(self.filtered_df.columns.tolist())}")
        filename_column = input("请输入包含文件名的列名: ").strip()

        if filename_column not in self.filtered_df.columns:
            print(f"❌ 错误：列'{filename_column}'不存在")
            return

        # 获取文件名列表
        file_list = self.filtered_df[filename_column].dropna().astype(str).unique().tolist()
        file_list.sort(key=str.upper)  # Windows风格排序

        print(f"\n✓ 提取到 {len(file_list)} 个文件名")

        # 输入源文件夹
        print("\n请指定源文件夹 (包含原始的.cif文件):")
        source_folder = input("源文件夹路径: ").strip()

        if not os.path.exists(source_folder):
            print(f"❌ 错误：文件夹不存在: {source_folder}")
            return

        # 输入目标文件夹
        print("\n请指定目标文件夹 (将复制筛选的.cif文件到这里):")
        dest_folder = input("目标文件夹路径: ").strip()

        # 创建目标文件夹
        os.makedirs(dest_folder, exist_ok=True)

        # 构建源文件夹中所有文件的映射
        print("\n🔍 扫描源文件夹中的文件...")
        file_map = {}
        for root, dirs, files in os.walk(source_folder):
            for file in files:
                file_map[file.lower()] = os.path.join(root, file)
        print(f"✓ 发现 {len(file_map)} 个文件")

        # 复制文件
        print("\n🚀 开始复制文件...")
        copied = 0
        missing = 0
        missing_list = []

        for i, filename in enumerate(file_list, 1):
            # 处理文件名后缀
            if not filename.lower().endswith('.cif'):
                cif_filename = filename + '.cif'
            else:
                cif_filename = filename

            # 查找文件
            source_file = file_map.get(cif_filename.lower())

            if source_file:
                try:
                    dest_file = os.path.join(dest_folder, os.path.basename(source_file))
                    shutil.copy2(source_file, dest_file)
                    copied += 1
                    if i % 50 == 0 or i == len(file_list):
                        print(f"  进度: {i}/{len(file_list)} ({i/len(file_list)*100:.1f}%)")
                except Exception as e:
                    print(f"  ❌ 复制失败 {cif_filename}: {e}")
                    missing += 1
                    missing_list.append(cif_filename)
            else:
                missing += 1
                missing_list.append(cif_filename)

        # 显示统计结果
        self.print_section("复制结果统计")
        print(f"总文件数: {len(file_list)}")
        print(f"成功复制: {copied} 个")
        print(f"未找到: {missing} 个")
        print(f"成功率: {copied/len(file_list)*100:.1f}%")
        print(f"保存位置: {dest_folder}")

        if missing > 0:
            print(f"\n⚠️  未找到的文件 (前10个):")
            for i, fname in enumerate(missing_list[:10], 1):
                print(f"  {i}. {fname}")
            if len(missing_list) > 10:
                print(f"  ... 还有 {len(missing_list) - 10} 个")

    def select_mode(self):
        """选择工作模式"""
        self.print_section("第一步：选择工作模式")
        print("请选择您需要的功能:")
        print("  1. 条件筛选模式 - 根据数值/文本条件筛选数据")
        print("  2. refcode提取模式 - 根据另一个CSV文件的refcode提取匹配数据")

        while True:
            choice = input("\n请选择模式 (1 或 2): ").strip()
            if choice == '1':
                self.mode = 'filter'
                print("✅ 已选择：条件筛选模式")
                break
            elif choice == '2':
                self.mode = 'extract'
                print("✅ 已选择：refcode提取模式")
                break
            else:
                print("❌ 错误：请输入 1 或 2")

    def run(self):
        """运行主程序"""
        self.print_header("MOF数据库筛选工具 - 改进版")
        print("\n功能说明:")
        print("  1. 选择工作模式")
        print("  2. 加载CSV文件")
        print("  3. 根据条件筛选数据 或 根据refcode提取数据")
        print("  4. 保存筛选结果")
        print("  5. 可选：复制对应的CIF文件")

        # 第一步：选择工作模式
        self.select_mode()

        # 第二步：加载CSV
        self.load_csv()

        # 第三步：根据模式执行不同操作
        if self.mode == 'filter':
            self.setup_filters()
        elif self.mode == 'extract':
            self.extract_by_refcode()

        # 第四步：保存结果
        csv_output = self.save_csv_result()

        # 第五步：可选复制文件
        if len(self.filtered_df) > 0:
            copy_files = input("\n是否需要复制筛选后的CIF文件? (y/n): ").strip().lower()
            if copy_files == 'y':
                self.copy_cif_files()

        # 完成
        self.print_header("操作完成！")
        print(f"\n✅ 统计信息:")
        print(f"   原始数据: {self.original_count} 行")
        print(f"   {'筛选' if self.mode == 'filter' else '提取'}后: {len(self.filtered_df)} 行")
        if self.mode == 'filter':
            print(f"   保留比例: {len(self.filtered_df)/self.original_count*100:.1f}%")
        if csv_output:
            print(f"\n📄 输出文件: {csv_output}")
        print("\n" + "=" * 70)

if __name__ == "__main__":
    tool = MOFFilterTool()
    tool.run()
