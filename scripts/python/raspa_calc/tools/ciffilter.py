#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MOF数据库筛选工具 - 改进版
功能：根据CSV条件筛选数据，并可选复制对应的CIF文件
"""

import os
import re
import shutil
from pathlib import Path

import pandas as pd

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
        print("      支持两种输入：逐条条件 / 表达式 (AND/OR、区间、多值 in 列表)")
        print("      直接按回车可以结束条件设置")

        self.filtered_df = self.df.copy()  # 创建副本避免警告

        # 优先表达式输入
        use_expr = input("\n是否使用表达式输入? (y=表达式 / 回车=逐条添加): ").strip().lower()
        if use_expr in ['y', 'yes', 'exp', 'expr']:
            success = self.apply_expression_filters()
            if success:
                print(f"\n✅ 筛选完成")
                print(f"   原始数据: {self.original_count} 行")
                print(f"   筛选后: {len(self.filtered_df)} 行")
                print(f"   保留比例: {len(self.filtered_df)/self.original_count*100:.1f}%")
                return

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

    def apply_expression_filters(self):
        """使用表达式一次性输入筛选条件"""
        self.print_section("表达式输入模式")
        print("支持语法示例:")
        print("  • 比较: PLD > 5, Density (g/cm3) <= 1.2, Metal Types = Co")
        print("  • 算数: `PLD` * 2 > 10, (ColA + ColB) / 2 > 0.5 (复杂列名请用反引号`包裹)")
        print("  • 区间: 4 <= LCD  <= 8")
        print("  • 多值: Metal Types in [Co,Ni,Zn]  或  KH_Classes in [weak,none]")
        print("  • 逻辑: 用 AND / OR 连接，支持括号。例：PLD>5 AND (LCD >=4 OR Metal Types in [Co,Ni])")

        while True:
            expr = input("\n请输入筛选表达式 (回车取消): ").strip()
            if not expr:
                print("ℹ️  未输入表达式，切换回逐条添加模式")
                return False

            try:
                mask = self.parse_expression(expr)
                self.filtered_df = self.filtered_df[mask].copy()
                print(f"✅ 表达式已应用，当前数据行数: {len(self.filtered_df)}")
                return True
            except Exception as e:
                print(f"❌ 表达式解析失败: {e}")
                retry = input("是否重新输入表达式? (y/n): ").strip().lower()
                if retry not in ['y', 'yes']:
                    return False

    def parse_expression(self, expr):
        """解析表达式为布尔掩码"""
        tokens = self._tokenize_expression(expr)
        if not tokens:
            raise ValueError("表达式为空")
        return self._evaluate_tokens(tokens)

    def _tokenize_expression(self, expr):
        """将表达式拆分为条件/逻辑/括号"""
        tokens = []
        pattern = re.compile(r'\s*(\(|\)|AND|OR)\s*', flags=re.IGNORECASE)
        pos = 0

        while pos < len(expr):
            m = pattern.match(expr, pos)
            if m:
                tok = m.group(1).upper()
                tokens.append(tok)
                pos = m.end()
            else:
                next_m = pattern.search(expr, pos)
                if next_m:
                    tokens.append(expr[pos:next_m.start()].strip())
                    pos = next_m.start()
                else:
                    tokens.append(expr[pos:].strip())
                    break

        return [t for t in tokens if t]

    def _evaluate_tokens(self, tokens):
        """用栈计算表达式 (AND 优先于 OR)"""
        def precedence(op):
            return 2 if op == 'AND' else 1

        def apply_op(op, b, a):
            if op == 'AND':
                return a & b
            elif op == 'OR':
                return a | b
            else:
                raise ValueError(f"未知逻辑运算符: {op}")

        values = []
        ops = []

        for tok in tokens:
            if tok == '(':
                ops.append(tok)
            elif tok == ')':
                while ops and ops[-1] != '(':
                    op = ops.pop()
                    b = values.pop()
                    a = values.pop()
                    values.append(apply_op(op, b, a))
                if not ops:
                    raise ValueError("括号不匹配")
                ops.pop()  # 弹出 '('
            elif tok in ('AND', 'OR'):
                while ops and ops[-1] in ('AND', 'OR') and precedence(ops[-1]) >= precedence(tok):
                    op = ops.pop()
                    b = values.pop()
                    a = values.pop()
                    values.append(apply_op(op, b, a))
                ops.append(tok)
            else:
                values.append(self._condition_to_mask(tok))

        while ops:
            op = ops.pop()
            if op == '(':
                raise ValueError("括号不匹配")
            b = values.pop()
            a = values.pop()
            values.append(apply_op(op, b, a))

        if len(values) != 1:
            raise ValueError("表达式解析异常，请检查语法")
        return values[0]

    def _resolve_series(self, expr):
        """解析列名或表达式为Series"""
        df = self.filtered_df
        expr = expr.strip()
        
        # 1. 尝试直接作为列名
        if expr in df.columns:
            return df[expr]
            
        # 2. 尝试作为表达式求值
        try:
            return df.eval(expr)
        except Exception:
            raise ValueError(f"无法解析列或表达式: {expr} (若是带空格的列名参与运算，请使用反引号包裹，如 `Col Name`)")

    def _condition_to_mask(self, cond):
        """将单个条件字符串转换为布尔掩码"""
        df = self.filtered_df
        if df is None or df.empty:
            raise ValueError("数据为空，无法应用条件")

        # 区间：min <= col <= max
        range_pat = re.compile(
            r'^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*<=\s*(.+?)\s*<=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)$'
        )
        in_pat = re.compile(r'^(.*?)\s+in\s+\[(.+)\]$', flags=re.IGNORECASE)
        in_paren_pat = re.compile(r'^(.*?)\s+in\s+\((.+)\)$', flags=re.IGNORECASE)
        compare_pat = re.compile(r'^(.*?)\s*(==|>=|<=|!=|=|>|<)\s*(.+)$')

        cond = cond.strip()

        range_match = range_pat.match(cond)
        if range_match:
            min_val = float(range_match.group(1))
            mid_expr = range_match.group(2).strip()
            max_val = float(range_match.group(3))
            
            series = self._resolve_series(mid_expr)
            series_num = pd.to_numeric(series, errors='coerce')
            return (series_num >= min_val) & (series_num <= max_val)

        in_match = in_pat.match(cond) or in_paren_pat.match(cond)
        if in_match:
            left_expr = in_match.group(1).strip()
            raw_values = [v.strip() for v in in_match.group(2).split(',')]
            values = [self._parse_value(v) for v in raw_values if v != '']
            
            series = self._resolve_series(left_expr)
            
            if pd.api.types.is_numeric_dtype(series):
                numeric_values = []
                for v in values:
                    if isinstance(v, (int, float)):
                        numeric_values.append(float(v))
                    else:
                        raise ValueError(f"左侧是数值型，列表中包含非数值: {v}")
                series_num = pd.to_numeric(series, errors='coerce')
                return series_num.isin(numeric_values)
            else:
                values_lower = [str(v).lower() for v in values]
                return series.astype(str).str.lower().isin(values_lower)

        compare_match = compare_pat.match(cond)
        if compare_match:
            left_raw = compare_match.group(1).strip()
            op = compare_match.group(2)
            right_raw = compare_match.group(3).strip()
            
            left_series = self._resolve_series(left_raw)
            
            # 解析右侧
            try:
                # 优先尝试作为数值
                right_val = float(right_raw)
            except ValueError:
                # 尝试作为表达式/列
                try:
                    right_val = df.eval(right_raw)
                except Exception:
                    # 只有当右侧确实像是一个字符串字面量时才fallback
                    right_val = self._parse_value(right_raw)

            if pd.api.types.is_numeric_dtype(left_series):
                series_num = pd.to_numeric(left_series, errors='coerce')
                # 如果右侧是Series，也要确保是数值
                if isinstance(right_val, pd.Series):
                    if pd.api.types.is_numeric_dtype(right_val):
                        right_val = pd.to_numeric(right_val, errors='coerce')
                    else:
                        raise ValueError("左侧是数值，右侧列是非数值")
                elif not isinstance(right_val, (int, float)):
                     try:
                         right_val = float(right_val)
                     except ValueError:
                         raise ValueError(f"左侧是数值型，右侧不是数值: {right_raw}")
                
                return self._compare_numeric(series_num, op, right_val)
            else:
                series_str = left_series.astype(str)
                return self._compare_text(series_str, op, right_val)

        raise ValueError(f"无法解析的条件: {cond}")

    def _compare_numeric(self, series, op, value):
        """数值比较"""
        if op == '>':
            return series > value
        elif op == '<':
            return series < value
        elif op in ('=', '=='):
            return series == value
        elif op == '>=':
            return series >= value
        elif op == '<=':
            return series <= value
        elif op == '!=':
            return series != value
        else:
            raise ValueError(f"未知比较符: {op}")

    def _compare_text(self, series, op, value):
        """文本比较（不区分大小写）"""
        series_lower = series.str.lower()
        
        if isinstance(value, pd.Series):
            value_lower = value.astype(str).str.lower()
        else:
            value_lower = str(value).lower()
            
        if op == '>':
            return series_lower > value_lower
        elif op == '<':
            return series_lower < value_lower
        elif op in ('=', '=='):
            return series_lower == value_lower
        elif op == '>=':
            return series_lower >= value_lower
        elif op == '<=':
            return series_lower <= value_lower
        elif op == '!=':
            return series_lower != value_lower
        else:
            raise ValueError(f"未知比较符: {op}")

    def _parse_value(self, raw):
        """将字符串解析为数字或原样字符串"""
        cleaned = raw.strip().strip('"').strip("'")
        try:
            return float(cleaned)
        except ValueError:
            return cleaned

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
