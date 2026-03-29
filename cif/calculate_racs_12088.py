import os
import glob
import json
import shutil
import tempfile
import traceback

import sys
import multiprocessing
from functools import partial

# 限制 OpenBLAS/MKL/OMP 线程数，防止多进程时线程冲突
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

# 设置 BABEL_DATADIR 环境变量以解决 Open Babel 警告
# 自动定位到当前环境下的 openbabel 数据目录
def setup_babel_env():
    babel_data_dir = os.path.join(sys.prefix, "Lib", "site-packages", "openbabel", "bin", "data")
    if os.path.exists(babel_data_dir):
        os.environ["BABEL_DATADIR"] = babel_data_dir
    return babel_data_dir

# 在主进程中设置一次
setup_babel_env()

def process_single_file(cif_file):
    """
    单个文件处理函数，将在子进程中运行。
    """
    # 确保子进程也有环境变量
    setup_babel_env()

    file_name = os.path.basename(cif_file)
    original_cwd = os.getcwd()

    # 尝试导入 RACs (需要在子进程中导入)
    try:
        from CoREMOF.calculation.mof_features import RACs
    except ImportError:
        return file_name, None, "ImportError: Could not import RACs"

    # 创建进程独占的临时目录
    # 注意：RACs 函数会在当前工作目录下创建名为 'tmp_rac' 的文件夹
    # 为了避免多进程冲突，我们需要为每个进程/任务创建一个独立的临时目录，并切换工作目录到那里
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # 复制 CIF 文件到临时目录
            temp_cif_path = os.path.join(temp_dir, file_name)
            shutil.copy(cif_file, temp_cif_path)

            # 切换工作目录到临时目录，这样 RACs 生成的 'tmp_rac' 就在这里，互不干扰
            os.chdir(temp_dir)

            try:
                # 计算 RACs
                rac_data = RACs(temp_cif_path)
                return file_name, rac_data, None
            except Exception as e:
                return file_name, None, str(e)
            finally:
                # 切回原目录 (虽然是在临时目录上下文外，但为了安全)
                os.chdir(original_cwd)

    except Exception as e:
        return file_name, None, f"SystemError: {str(e)}"

def main():
    # 指定目标目录
    target_dir = r"/home/zjp/raspa2-calc/.raspa_tools/cif/12088cif_LCD_5-12"

    # 检查目录是否存在
    if not os.path.exists(target_dir):
        print(f"Error: Directory not found: {target_dir}")
        return

    # 获取目录下所有的 .cif 文件
    cif_files = glob.glob(os.path.join(target_dir, "*.cif"))

    if not cif_files:
        print(f"No .cif files found in {target_dir}")
        return

    print(f"Found {len(cif_files)} CIF files. Starting parallel RACs calculation...")

    # 确定进程数，使用 20 个进程防止资源耗尽
    num_processes = 20
    print(f"Using {num_processes} processes.")

    results = {}
    errors = []

    # 使用 multiprocessing.Pool 进行并行计算
    with multiprocessing.Pool(processes=num_processes) as pool:
        # 使用 imap_unordered 可以实时获取结果（虽然这里我们只是打印进度）
        # chunksize 可以稍微调大一点以减少 IPC 开销
        total_files = len(cif_files)
        for i, (file_name, data, error) in enumerate(pool.imap_unordered(process_single_file, cif_files, chunksize=1)):
            if data:
                results[file_name] = data
                print(f"[{i+1}/{total_files}] Success: {file_name}")
            else:
                errors.append((file_name, error))
                print(f"[{i+1}/{total_files}] Failed: {file_name} - {error}")

    print(f"\nCalculation finished. Success: {len(results)}, Failed: {len(errors)}")

    # 将所有结果保存到 JSON 文件
    output_json = os.path.join(os.path.dirname(__file__), "racs_results_12088.json")
    try:
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4, ensure_ascii=False)
        print(f"Results saved to JSON: {output_json}")
    except Exception as e:
        print(f"Error saving results to JSON: {e}")

    # 将所有结果保存到 CSV 文件
    output_csv = os.path.join(os.path.dirname(__file__), "racs_results_12088.csv")
    try:
        if results:
            import csv

            # 展平数据结构以便保存为 CSV
            flattened_data = []
            all_keys = set()

            for file_name, data in results.items():
                row = {"filename": file_name}
                # data 结构为 {'Metal': {...}, 'Linker': {...}, ...}
                for category in data:
                    if isinstance(data[category], dict):
                        for k, v in data[category].items():
                            row[k] = v
                            all_keys.add(k)
                flattened_data.append(row)

            # 排序表头
            fieldnames = ["filename"] + sorted(list(all_keys))

            with open(output_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(flattened_data)

            print(f"Results saved to CSV: {output_csv}")
        else:
            print("No results to save to CSV.")

    except Exception as e:
        print(f"Error saving results to CSV: {e}")

    # 如果有错误，保存错误日志
    if errors:
        error_log = os.path.join(os.path.dirname(__file__), "racs_errors_12088.log")
        with open(error_log, 'w', encoding='utf-8') as f:
            for name, err in errors:
                f.write(f"{name}: {err}\n")
        print(f"Errors saved to: {error_log}")

if __name__ == "__main__":
    main()
