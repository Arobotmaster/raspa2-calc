import copy
import json
import logging
import os
import re
import subprocess
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import nullcontext

import pandas as pd

from raspa_calc.algorithms.calculate_params import load_cache, process_structure_file, save_cache

from . import state
from .cif import count_numbered_labels, locate_cif_file
from .env import _env_flag, _positive_int, get_raspa_version_from_env, load_raspa3_config
from .framework import _process_framework_wrapper, check_structure_files
from .inputs import get_computation_setup, get_directory_setup
from .logging_utils import logger, quiet_console
from .templates import update_all_files


def _parse_submit_index(line):
    match = re.search(r"正在提交(?:作业\s*|第)(\d+)", line)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _should_print_submit_line(line):
    important_markers = (
        "错误",
        "失败",
        "⚠️",
        "❌",
        "警告",
        "WARNING",
        "Error",
        "ERROR",
        "开始提交计算任务",
        "使用CPU核心数",
        "提交模式",
        "开始逐个提交作业",
        "job array",
        "Job array",
        "节点分配计划",
        "所有作业已提交完成",
        "提示",
        "检测到",
    )
    return any(marker in line for marker in important_markers)


def main():
    try:
        raspa_version = get_raspa_version_from_env()
        raspa3_config = load_raspa3_config() if raspa_version == "raspa3" else {}

        logger.info(f"=== RASPA高通量计算设置 ({raspa_version.upper()}) ===")

        print(f"\n步骤1：初始化设置 (RASPA版本: {raspa_version.upper()})")

        framework_column = "refcode"
        if len(sys.argv) == 3:
            csv_file = sys.argv[1]
            column_number = sys.argv[2]
            framework_column = os.environ.get("RASPA_FRAMEWORK_COLUMN", "refcode")
            logger.info("从命令行参数获取CSV文件信息")
        else:
            csv_file = os.environ.get("RASPA_CSV_FILE")
            framework_column = os.environ.get("RASPA_FRAMEWORK_COLUMN", "refcode")

            if not csv_file:
                logger.error("错误：未找到CSV文件路径，请在配置文件中设置csv_file_path")
                sys.exit(1)

            column_number = framework_column
            logger.info("从环境变量获取CSV文件信息")

        if not os.path.exists(csv_file):
            logger.error(f"错误：找不到CSV文件 {csv_file}")
            sys.exit(1)

        topdir = os.path.abspath(os.getcwd())
        subdir = get_directory_setup()
        state.CURRENT_TOPDIR = topdir
        state.CURRENT_SUBDIR = subdir

        if not os.path.exists(os.path.join(topdir, subdir)):
            try:
                os.makedirs(os.path.join(topdir, subdir))
            except Exception as e:
                logger.error(f"无法创建目录: {e}")
                sys.exit(1)

        print("\n步骤2：处理CSV文件")
        try:
            try:
                df = pd.read_csv(csv_file, encoding="utf-8-sig")
            except UnicodeDecodeError:
                try:
                    df = pd.read_csv(csv_file, encoding="utf-8")
                except UnicodeDecodeError:
                    df = pd.read_csv(csv_file, encoding="gbk")
            df = df.dropna(subset=[df.columns[0]])

            if column_number.isdigit():
                col_index = int(column_number) - 1
                if 0 <= col_index < len(df.columns):
                    framework_names = df[df.columns[col_index]].dropna().tolist()
                else:
                    logger.error(f"列号 {column_number} 超出范围")
                    sys.exit(1)
            else:
                if column_number in df.columns:
                    framework_names = df[column_number].dropna().tolist()
                else:
                    logger.error(f"列名 '{column_number}' 不存在于CSV文件中")
                    logger.info(f"可用的列名: {list(df.columns)}")
                    sys.exit(1)

            framework_names = [name for name in framework_names if str(name).strip()]
            total_tasks = len(framework_names)
            initial_total_tasks = total_tasks

            if total_tasks == 0:
                logger.error("没有找到有效的框架结构，请检查CSV文件")
                sys.exit(1)

            logger.info(f"找到 {total_tasks} 个有效框架结构")

            if raspa_version == "raspa3":
                cif_dir = raspa3_config.get("cif_base_path", "")
                if not cif_dir:
                    cif_dir = os.environ.get("RASPA_CIF_DIR", "")
                if not cif_dir:
                    default_cif_dir = "/home/zjp/anaconda3/envs/raspa3/share/raspa3/framework"
                    cif_dir = input(f"\n请输入CIF文件基础路径 (默认为'{default_cif_dir}'): ").strip()
                    if not cif_dir:
                        cif_dir = default_cif_dir
                else:
                    logger.info(f"使用配置文件中的CIF基础路径 (RASPA3): {cif_dir}")
            else:
                cif_dir = os.environ.get("RASPA_CIF_DIR")
                if not cif_dir:
                    current_dir = os.getcwd()
                    default_cif_dir = os.path.join(current_dir, "data", "cif")
                    cif_dir = input(f"\n请输入CIF文件目录 (默认为'{default_cif_dir}'): ").strip()
                    if not cif_dir:
                        cif_dir = default_cif_dir
                else:
                    logger.info(f"使用配置文件中的CIF目录: {cif_dir}")

            if not os.path.exists(cif_dir):
                logger.warning(f"CIF目录不存在: {cif_dir}")
                create_dir = input("是否创建该目录? (y/n): ").strip().lower()
                if create_dir == "y":
                    try:
                        os.makedirs(cif_dir, exist_ok=True)
                        logger.info(f"已创建目录: {cif_dir}")
                    except Exception as e:
                        logger.error(f"创建目录失败: {e}")

            logger.info(f"将使用CIF目录: {cif_dir}")

            logger.info("检查框架对应的CIF文件...")
            missing_cifs = []
            skipped_missing_cifs = 0
            found_cifs = []
            framework_cif_paths = {}

            for framework in framework_names:
                cif_file = locate_cif_file(framework, cif_dir)
                if cif_file:
                    found_cifs.append(framework)
                    framework_cif_paths[framework] = cif_file
                else:
                    missing_cifs.append(framework)

            if missing_cifs:
                logger.warning(f"以下 {len(missing_cifs)} 个框架没有对应的CIF文件:")
                for i, missing in enumerate(missing_cifs[:10], 1):
                    logger.warning(f"  {i}. {missing}")
                if len(missing_cifs) > 10:
                    logger.warning(f"  ... 及其他 {len(missing_cifs) - 10} 个")

                skipped_missing_cifs = len(missing_cifs)
                logger.warning("上述框架将被自动跳过，程序继续处理其余结构。")

            framework_names = found_cifs
            total_tasks = len(framework_names)

            if total_tasks == 0:
                logger.error("所有框架均缺少CIF文件，无法继续计算。")
                sys.exit(1)

            logger.info(f"共找到 {len(found_cifs)} 个框架对应的CIF文件")

            label_issues = []
            total_label_issues = 0

            logger.info("正在检查 CIF 文件标签格式...")

            check_tasks = []
            for framework in framework_names:
                cif_path = framework_cif_paths.get(framework)
                if not cif_path:
                    continue
                if "cleaned_cif" in os.path.normpath(cif_path).split(os.sep):
                    continue
                check_tasks.append((framework, cif_path))

            if check_tasks:
                try:
                    cpu_count = os.cpu_count() or 2
                except Exception:
                    cpu_count = 2
                max_workers = min(16, cpu_count)

                with ProcessPoolExecutor(max_workers=max_workers) as executor:
                    future_to_fw = {
                        executor.submit(count_numbered_labels, cif_path): (framework, cif_path)
                        for framework, cif_path in check_tasks
                    }

                    for future in as_completed(future_to_fw):
                        framework, cif_path = future_to_fw[future]
                        try:
                            issue_count = future.result()
                            if issue_count > 0:
                                label_issues.append((framework, cif_path, issue_count))
                                total_label_issues += issue_count
                        except Exception:
                            pass

            if label_issues:
                preview_limit = 10
                logger.warning(
                    f"检测到 {len(label_issues)} 个 CIF 文件的 _atom_site_label 含编号，共 {total_label_issues} 条标签存在编号。"
                )
                for fw, path, cnt in label_issues[:preview_limit]:
                    logger.warning(f"  - {fw}: {cnt} 个编号标签 ({path})")
                if len(label_issues) > preview_limit:
                    logger.warning(f"  ... 仅展示前 {preview_limit} 个框架，另有 {len(label_issues) - preview_limit} 个未列出")

                user_choice = input("是否使用 clean_cif_labels.py 自动去除编号? (y/n): ").strip().lower()
                if user_choice != "y":
                    logger.error("用户拒绝自动清理 CIF 标签，程序终止。请先处理标签后重新运行。")
                    sys.exit(1)

                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                script_path = os.path.join(base_dir, "clean_cif_labels.py")
                target_files = [os.path.basename(path) for _, path, _ in label_issues]
                logger.info(
                    "运行标签清理脚本（就地处理有编号的文件）: "
                    f"{script_path} {cif_dir} --in-place --files {', '.join(target_files)}"
                )
                cmd = [sys.executable, script_path, cif_dir, "--in-place", "--files", *target_files]
                result = subprocess.run(cmd)
                if result.returncode != 0:
                    logger.error("标签清理脚本执行失败，程序终止。")
                    sys.exit(1)

                missing_cleaned = [f for f in target_files if not os.path.exists(os.path.join(cif_dir, f))]
                if missing_cleaned:
                    logger.error(f"以下文件未成功完成就地清理: {', '.join(missing_cleaned)}")
                    sys.exit(1)

                logger.info(f"已完成 {len(target_files)} 个 CIF 的就地清理。")

        except Exception as e:
            logger.error(f"处理CSV文件时出错: {e}")
            logger.debug(traceback.format_exc())
            sys.exit(1)

        cpu_cores, cutoff, void_csv_file, void_fraction_column, template_path, molecule_name, _ = get_computation_setup(
            total_tasks, cif_dir
        )

        print("\n步骤3：配置摘要")
        logger.info("计算参数:")
        logger.info(f"- 输出目录: {subdir}")
        logger.info(f"- 处理框架数: {total_tasks}")
        logger.info(f"- CPU核心数: {cpu_cores}")
        logger.info(f"- 截断半径: {cutoff}")
        logger.info(f"- 分子名称: {molecule_name}")
        logger.info(f"- CIF文件目录: {cif_dir}")
        if template_path:
            logger.info(f"- 自定义模板路径: {template_path}")
        if void_csv_file and void_fraction_column:
            logger.info(f"- 孔隙率CSV文件: {void_csv_file}")
            logger.info(f"- 孔隙率列名: {void_fraction_column}")

        if raspa_version == "raspa3":
            print("\n=== 生成的 simulation.json 示例 (RASPA3) ===\n")
        else:
            print("\n=== 生成的 simulation.input 示例 (RASPA2) ===\n")

        if framework_names:
            first_framework = framework_names[0]

            try:
                structure_file = check_structure_files(first_framework, cif_dir)
                if structure_file:
                    success, unit_cells, void_fraction = process_structure_file(
                        structure_file,
                        cutoff,
                        csv_file=void_csv_file,
                        void_fraction_column=void_fraction_column,
                        framework_column=framework_column,
                    )

                    if success:
                        molecule_list = molecule_name.split() if isinstance(molecule_name, str) else [molecule_name]

                        if raspa_version == "raspa3":
                            template_file = template_path if template_path and os.path.isfile(template_path) else None
                            if not template_file:
                                tool_dir = os.environ.get("HOME", "") + "/raspa2-calc/.raspa_tools"
                                template_file = os.path.join(tool_dir, "raspa3json", "CO2", "simulation.json")

                            if os.path.exists(template_file):
                                with open(template_file, "r") as f:
                                    sim_config = json.load(f)

                                sim_config = copy.deepcopy(sim_config)

                                if "Systems" in sim_config and len(sim_config["Systems"]) > 0:
                                    sim_config["Systems"][0]["Name"] = structure_file
                                    sim_config["Systems"][0]["NumberOfUnitCells"] = list(unit_cells)
                                    sim_config["Systems"][0]["HeliumVoidFraction"] = void_fraction

                                if "Components" in sim_config:
                                    for i, component in enumerate(sim_config["Components"]):
                                        if i < len(molecule_list):
                                            component["Name"] = molecule_list[i]
                                        elif molecule_list:
                                            component["Name"] = molecule_list[0]

                                mser_enable = os.environ.get("RASPA_MSER_ENABLE", "false").lower() == "true"
                                if mser_enable:
                                    try:
                                        mser_add_cycles = int(os.environ.get("RASPA_MSER_ADD_CYCLES", "500"))
                                    except ValueError:
                                        mser_add_cycles = 500
                                    sim_config["NumberOfCycles"] = mser_add_cycles
                                    sim_config["NumberOfInitializationCycles"] = 0
                                    sim_config["NumberOfEquilibrationCycles"] = 0
                                    sim_config["PrintEvery"] = 1

                                sim_config.pop("WriteBinaryRestartEvery", None)
                                sim_config.pop("RestartFromBinaryFile", None)

                                sim_text = json.dumps(sim_config, indent=2)
                                sim_lines = sim_text.splitlines()
                                preview_lines = 60
                                print("\n".join(sim_lines[:preview_lines]))
                                if len(sim_lines) > preview_lines:
                                    print(f"... (共{len(sim_lines)}行，仅显示前{preview_lines}行)")

                            print("\n" + "=" * 50)
                            print(f"📦 此示例使用框架: {first_framework}")
                            print(f"📦 CIF 文件路径: {structure_file}")
                            print(f"📦 NumberOfUnitCells: {list(unit_cells)}")
                            print(f"📦 孔隙率: {void_fraction}")
                            if len(molecule_list) > 1:
                                print(f"📦 多组分分子: {', '.join(molecule_list)}")
                            else:
                                print(f"📦 分子名称: {molecule_list[0]}")

                            json_dir = raspa3_config.get("json_dir", "")
                            if json_dir:
                                print(f"📦 JSON 文件目录: {json_dir}")
                            print("=" * 50)
                        else:
                            template_file = template_path if template_path and os.path.isfile(template_path) else None
                            if os.path.exists(template_file):
                                with open(template_file, "r") as f:
                                    template_content = f.read()

                                lines = template_content.split("\n")

                                for i, line in enumerate(lines):
                                    if line.startswith("FrameworkName"):
                                        lines[i] = f"FrameworkName {first_framework}"
                                    elif line.startswith("UnitCells"):
                                        lines[i] = f"UnitCells {unit_cells[0]} {unit_cells[1]} {unit_cells[2]}"
                                    elif line.startswith("HeliumVoidFraction"):
                                        lines[i] = f"HeliumVoidFraction {void_fraction}"
                                    elif line.startswith("Component ") and "MoleculeName" in line:
                                        parts = line.split()
                                        if len(parts) >= 3 and parts[0] == "Component" and parts[2] == "MoleculeName":
                                            try:
                                                component_idx = int(parts[1])
                                                if component_idx < len(molecule_list):
                                                    molecule = molecule_list[component_idx]
                                                    prefix = line[: line.find("MoleculeName") + len("MoleculeName")]
                                                    lines[i] = f"{prefix}   {molecule}"
                                                else:
                                                    molecule = molecule_list[0]
                                                    prefix = line[: line.find("MoleculeName") + len("MoleculeName")]
                                                    lines[i] = f"{prefix}   {molecule}"
                                            except (ValueError, IndexError):
                                                pass

                                print("\n".join(lines[:50]))
                                if len(lines) > 50:
                                    print(f"... (共{len(lines)}行，仅显示前50行)")

                            print("\n" + "=" * 50)
                            print(f"📦 此示例使用框架: {first_framework}")
                            print(f"📦 UnitCells: {unit_cells[0]} {unit_cells[1]} {unit_cells[2]}")
                            print(f"📦 孔隙率: {void_fraction}")
                            if len(molecule_list) > 1:
                                print(f"📦 多组分分子: {', '.join(molecule_list)}")
                            else:
                                print(f"📦 分子名称: {molecule_list[0]}")
                            print("=" * 50)

            except Exception as e:
                logger.warning(f"无法生成示例: {e}")

        if input("\n确认这些设置正确吗？(y/n): ").lower() != "y":
            logger.info("程序已终止")
            sys.exit(0)

        use_cache = _env_flag("RASPA_USE_CIF_CACHE", False)
        result_cache = None
        cache_file = os.environ.get("RASPA_CIF_CACHE_PATH") or os.path.join(topdir, "params_cache.json")

        if use_cache:
            result_cache = load_cache(cache_file)
            if result_cache:
                logger.info(f"启用 CIF 参数缓存 (已加载 {len(result_cache)} 条记录) | 路径: {cache_file}")
            else:
                logger.info(f"启用 CIF 参数缓存 (无现有缓存) | 路径: {cache_file}")

        print(f"\n步骤4：处理结构文件 ({raspa_version.upper()})")
        successful_structures = 0
        from tqdm import tqdm

        json_dir = raspa3_config.get("json_dir", "") if raspa_version == "raspa3" else None

        quiet_mode = not _env_flag("RASPA_HT_VERBOSE", False)
        console_ctx = quiet_console(logging.WARNING) if quiet_mode else nullcontext()

        tasks = []
        for counter, framework_name in enumerate(framework_names, 1):
            if raspa_version == "raspa3":
                kwargs = {
                    "topdir": topdir,
                    "subdir": subdir,
                    "counter": counter,
                    "framework_name": framework_name,
                    "cutoff": cutoff,
                    "void_csv_file": void_csv_file,
                    "void_fraction_column": void_fraction_column,
                    "template_path": template_path,
                    "molecule_name": molecule_name,
                    "cif_base_path": cif_dir,
                    "json_dir": json_dir,
                    "framework_column": framework_column,
                    "result_cache": result_cache if result_cache is not None else {},
                }
                tasks.append(("raspa3", kwargs))
            else:
                kwargs = {
                    "topdir": topdir,
                    "subdir": subdir,
                    "counter": counter,
                    "framework_name": framework_name,
                    "cutoff": cutoff,
                    "void_csv_file": void_csv_file,
                    "void_fraction_column": void_fraction_column,
                    "template_path": template_path,
                    "molecule_name": molecule_name,
                    "cif_dir": cif_dir,
                    "framework_column": framework_column,
                    "result_cache": result_cache if result_cache is not None else {},
                }
                tasks.append(("raspa2", kwargs))

        with console_ctx:
            try:
                cpu_count = os.cpu_count() or 2
            except Exception:
                cpu_count = 2
            max_workers = min(32, cpu_count)
            logger.info(f"启用并行处理结构文件，使用 {max_workers} 个进程")

            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(_process_framework_wrapper, task) for task in tasks]

                with tqdm(total=len(tasks), desc="处理进度", unit="结构") as pbar:
                    for future in as_completed(futures):
                        try:
                            success, new_cache = future.result()
                            if success:
                                successful_structures += 1

                            if result_cache is not None and new_cache:
                                result_cache.update(new_cache)
                        except Exception as e:
                            logger.error(f"任务执行异常: {e}")

                        pbar.update(1)

        if use_cache and result_cache is not None:
            save_cache(result_cache, cache_file)

        print("\n步骤5：处理结果")
        if successful_structures == 0:
            logger.error("没有成功处理任何结构文件，无法继续计算")
            logger.error("请确保wei目录或cif目录中存在所需的结构文件")
            logger.error("计算被取消")
            sys.exit(1)

        actual_cores = min(cpu_cores, successful_structures) if successful_structures != total_tasks else cpu_cores
        logger.info(
            f"准备更新配置文件: topdir={topdir}, total_tasks={successful_structures}, subdir={subdir}, actual_cores={actual_cores}"
        )
        if not update_all_files(topdir, successful_structures, subdir, actual_cores):
            logger.error("更新配置文件失败，程序终止")
            sys.exit(1)
        logger.info("配置文件更新完成")

        print("\n步骤6：执行总结")
        logger.info("计算任务设置完成:")
        logger.info(f"- 原始结构数: {initial_total_tasks}")
        logger.info(f"- 成功处理: {successful_structures} 个结构")
        if skipped_missing_cifs:
            logger.info(f"- 缺失CIF跳过: {skipped_missing_cifs} 个结构")
        logger.info(f"- 失败处理: {total_tasks - successful_structures} 个结构")
        logger.info(f"- 实际使用CPU核心数: {actual_cores}")
        logger.info("所有配置文件已更新，开始提交计算任务...")

        print("\n步骤7：提交计算任务")
        try:
            tool_dir = os.path.expanduser("~/raspa2-calc/.raspa_tools")
            tasksrun_script = os.path.join(tool_dir, "job_templates", "tasksrun.sh")

            if not os.path.exists(tasksrun_script):
                logger.error(f"找不到任务提交脚本: {tasksrun_script}")
                logger.info("请手动运行以下命令提交任务:")
                logger.info(f"bash {tasksrun_script} {actual_cores}")
                return

            os.environ["RASPA_WORK_DIR"] = topdir

            if "RASPA_CIF_DIR" in os.environ:
                logger.info(f"传递CIF目录环境变量: {os.environ['RASPA_CIF_DIR']}")
            else:
                logger.warning("RASPA_CIF_DIR环境变量未设置")

            env = os.environ.copy()
            print(f"将提交 {actual_cores} 个并行作业")
            with subprocess.Popen(
                [tasksrun_script, str(actual_cores)],
                cwd=topdir,
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
            else:
                logger.error("任务提交失败")
                logger.info("请手动运行以下命令提交任务:")
                logger.info(f"bash {tasksrun_script} {actual_cores}")

        except Exception as e:
            logger.error(f"提交任务时出错: {e}")
            logger.info("请手动运行以下命令提交任务:")
            logger.info(f"bash {tasksrun_script} {actual_cores}")

    except KeyboardInterrupt:
        logger.info("\n用户取消操作，程序已终止")
        sys.exit(130)
    except Exception as e:
        logger.error(f"程序执行时出错: {e}")
        logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
