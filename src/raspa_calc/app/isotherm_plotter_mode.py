import os
import re
import sys

from raspa_calc.runtime import config as config_module


def run_isotherm_plotter():
    """Run isotherm plotting mode."""
    print("\n=== 等温线绘制模式 ===")
    print("该功能将从RASPA计算结果中批量绘制所有MOF的等温吸附曲线")
    print()

    try:
        if config_module.config is None:
            config_module.load_runtime_config()

        try:
            import matplotlib  # noqa: F401
        except ImportError:
            print("❌ 缺少必需的依赖库: matplotlib")
            print("请运行以下命令安装:")
            print("  pip install matplotlib")
            sys.exit(1)

        work_dir = os.getcwd()
        print(f"📁 当前工作目录: {work_dir}")

        def _detect_result_signals(dir_path: str) -> tuple[int, int]:
            """
            Roughly detect RASPA result directories.

            Returns:
                (raspa2_count, raspa3_count)
            """
            raspa2_count = 0
            raspa3_count = 0

            try:
                # Check if dir_path itself contains output files (RASPA2 or RASPA3)
                # RASPA2: output_*.data directly or in Output/System_0
                # RASPA3: output_*.txt directly or in output
                
                # Check immediate subdirectories
                with os.scandir(dir_path) as it:
                    for entry in it:
                        if entry.is_dir():
                            # 1. Check for standard mc* naming
                            if re.match(r"^mc\d+", entry.name):
                                raspa2_count += 1
                                continue
                            
                            # 2. Check for RASPA2 structure (Output/System_0) in arbitrary named dirs
                            # This handles cases like COV_...__done
                            r2_out = os.path.join(entry.path, "Output", "System_0")
                            if os.path.isdir(r2_out):
                                # Check if any .data file exists
                                has_data = False
                                try:
                                    with os.scandir(r2_out) as sub_it:
                                        for f in sub_it:
                                            if f.name.endswith('.data') and f.name.startswith('output_'):
                                                has_data = True
                                                break
                                except OSError:
                                    pass
                                if has_data:
                                    raspa2_count += 1
                                    continue
                            
                            # 3. Check for RASPA3 structure (output/output_*.txt) in arbitrary named dirs
                            r3_out = os.path.join(entry.path, "output")
                            if os.path.isdir(r3_out):
                                try:
                                    with os.scandir(r3_out) as sub_it:
                                        for f in sub_it:
                                            if f.name.endswith('.txt') and f.name.startswith('output_'):
                                                raspa3_count += 1
                                                break
                                except OSError:
                                    pass

            except Exception:
                pass

            # Also check for centralized output folder pattern (RASPA3 often puts all txts in one output dir)
            # or if the current dir IS a simulation dir
            
            def _count_txt_in_output(output_dir: str) -> int:
                n = 0
                try:
                    if os.path.isdir(output_dir):
                        with os.scandir(output_dir) as it:
                            for f in it:
                                if f.is_file():
                                    name = f.name.lower()
                                    if name.startswith("output_") and name.endswith(".txt"):
                                        n += 1
                except Exception:
                    return 0
                return n

            def _count_data_in_output(output_dir: str) -> int:
                n = 0
                try:
                    if os.path.isdir(output_dir):
                        with os.scandir(output_dir) as it:
                            for f in it:
                                if f.is_file():
                                    name = f.name.lower()
                                    if name.startswith("output_") and name.endswith(".data"):
                                        n += 1
                except Exception:
                    return 0
                return n

            # Check local output/ (RASPA3)
            raspa3_count += _count_txt_in_output(os.path.join(dir_path, "output"))
            
            # Check local Output/System_0/ (RASPA2)
            raspa2_count += _count_data_in_output(os.path.join(dir_path, "Output", "System_0"))
            
            # Check current dir for direct files (loose files)
            raspa3_count += _count_txt_in_output(dir_path)
            raspa2_count += _count_data_in_output(dir_path)

            return raspa2_count, raspa3_count

        def _parse_selection(raw: str, max_idx: int) -> list[int]:
            raw = raw.strip().lower()
            if raw in {"all", "a", "全部"}:
                return list(range(1, max_idx))

            parts = re.split(r"[,\s]+", raw)
            indices = []
            for part in parts:
                if not part:
                    continue
                if "-" in part:
                    try:
                        left, right = part.split("-", 1)
                        start = int(left)
                        end = int(right)
                    except ValueError:
                        raise ValueError("invalid_range")
                    if start > end:
                        start, end = end, start
                    for idx in range(start, end + 1):
                        if idx not in indices:
                            indices.append(idx)
                else:
                    try:
                        idx = int(part)
                    except ValueError:
                        raise ValueError("invalid_index")
                    if idx not in indices:
                        indices.append(idx)

            if not indices:
                raise ValueError("empty")
            return indices

        param_screening_config = config_module.config.get("parameter_screening", {}) if config_module.config else {}
        default_output_dir = param_screening_config.get("output_directory", "等温线")

        possible_dirs = []

        for d in [default_output_dir, "等温线", "output", "calc_output", "isotherms", "."]:
            full_path = work_dir if d == "." else os.path.join(work_dir, d)
            if os.path.isdir(full_path):
                raspa2_count, raspa3_count = _detect_result_signals(full_path)
                if raspa2_count > 0 or raspa3_count > 0:
                    label = d
                    possible_dirs.append((label, full_path, raspa2_count, raspa3_count))

        if not possible_dirs:
            try:
                for entry in os.scandir(work_dir):
                    if not entry.is_dir():
                        continue
                    raspa2_count, raspa3_count = _detect_result_signals(entry.path)
                    if raspa2_count > 0 or raspa3_count > 0:
                        possible_dirs.append((entry.name, entry.path, raspa2_count, raspa3_count))
            except Exception:
                pass

        if possible_dirs:
            print(f"\n✓ 检测到 {len(possible_dirs)} 个包含计算结果的目录:")
            for i, (dirname, _, raspa2_count, raspa3_count) in enumerate(possible_dirs, 1):
                parts = []
                if raspa2_count > 0:
                    parts.append(f"{raspa2_count} 个RASPA2模拟/文件")
                if raspa3_count > 0:
                    parts.append(f"{raspa3_count} 个RASPA3输出文件")
                detail = "，".join(parts) if parts else "包含结果文件"
                suffix = "/" if dirname != "." else ""
                print(f"  {i}. {dirname}{suffix} ({detail})")
            print(f"  {len(possible_dirs) + 1}. 手动输入目录路径")
        else:
            print("\n⚠️  未检测到标准的计算结果目录")
            possible_dirs = []

        if possible_dirs:
            try:
                choice = input(
                    f"\n请选择要绘制的目录 (1-{len(possible_dirs) + 1}) [默认: 1，可多选如 1,3-5 或 all]: "
                ).strip()
                if not choice:
                    choice = "1"

                manual_idx = len(possible_dirs) + 1
                indices = _parse_selection(choice, manual_idx)

                for idx in indices:
                    if idx < 1 or idx > manual_idx:
                        raise ValueError("out_of_range")

                manual_paths = []
                if manual_idx in indices:
                    raw_paths = input("请输入目录路径 (可用逗号分隔多个): ").strip()
                    if not raw_paths:
                        print("❌ 未输入目录路径")
                        sys.exit(1)
                    raw_paths = raw_paths.replace(";", ",")
                    for p in [x.strip() for x in raw_paths.split(",") if x.strip()]:
                        if not os.path.isdir(p):
                            print(f"❌ 目录不存在: {p}")
                            sys.exit(1)
                        manual_paths.append(p)

                base_dirs = []
                for idx in indices:
                    if idx == manual_idx:
                        base_dirs.extend(manual_paths)
                    else:
                        base_dirs.append(possible_dirs[idx - 1][1])

                seen = set()
                base_dirs = [d for d in base_dirs if not (d in seen or seen.add(d))]

                if not base_dirs:
                    print("❌ 未选择有效目录")
                    sys.exit(1)
            except ValueError:
                print("❌ 无效的输入")
                sys.exit(1)
        else:
            manual_path = input("请输入包含计算结果的目录路径: ").strip()
            if not os.path.isdir(manual_path):
                print(f"❌ 目录不存在: {manual_path}")
                sys.exit(1)
            base_dirs = [manual_path]

        calc_config = config_module.config.get("calculation", {}) if config_module.config else {}

        print("\n📊 绘图参数配置:")
        print("   吸附类型: absolute (绝对吸附)")
        print("   单位: mol/kg")
        print("   压力单位: Pa")
        print("   x轴: 线性刻度")

        use_default = input("\n是否使用默认参数? (y/n) [默认: y]: ").strip().lower()

        if use_default in ["", "y", "yes"]:
            ads_type = "absolute"
            unit = "mol/kg"
            pressure_unit = "Pa"
            logx = False
        else:
            ads_type = input("吸附类型 (absolute/excess) [默认: absolute]: ").strip() or "absolute"
            unit = input("单位 (mol/kg, cm^3/g, mg/g, cm^3/cm^3) [默认: mol/kg]: ").strip() or "mol/kg"
            pressure_unit = input("压力单位 (Pa/bar) [默认: Pa]: ").strip() or "Pa"
            logx_input = input("使用对数x轴? (y/n) [默认: n]: ").strip().lower()
            logx = logx_input in ["y", "yes"]

        outdir = input("\n输出目录名 [默认: isotherms]: ").strip() or "isotherms"

        multi_mode = len(base_dirs) > 1
        outdir_mode = "per_dir"
        if multi_mode:
            print("\n📁 多目录输出方式:")
            print("   1. 每个结果目录下创建子目录")
            print("   2. 统一输出到当前目录下，按目录名分子目录")
            choice = input("请选择输出方式 (1/2) [默认: 1]: ").strip() or "1"
            if choice == "2":
                outdir_mode = "by_dirname"

        from .isotherm_plotter import main as plotter_main

        print("\n🚀 开始绘制等温线...")
        for i, base_dir in enumerate(base_dirs, 1):
            if multi_mode:
                if outdir_mode == "by_dirname":
                    label = os.path.basename(os.path.normpath(base_dir)) or "output"
                    outdir_path = os.path.join(work_dir, outdir, label)
                else:
                    outdir_path = os.path.join(base_dir, outdir)
            else:
                outdir_path = outdir

            print(f"\n[{i}/{len(base_dirs)}] 扫描目录: {base_dir}")
            print(f"[{i}/{len(base_dirs)}] 输出目录: {outdir_path}")

            args = [
                "--base-dir",
                base_dir,
                "--type",
                ads_type,
                "--unit",
                unit,
                "--pressure-unit",
                pressure_unit,
                "--outdir",
                outdir_path,
            ]

            if logx:
                args.append("--logx")
            else:
                args.append("--linearx")

            plotter_main(args)

    except ImportError as e:
        print(f"❌ 无法导入等温线绘制模块: {e}")
        print("请确保已正确安装 raspa_calc 包")
        print("可尝试运行: python -m raspa_calc.entrypoints.isotherm_plotter --help")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  用户取消操作")
        sys.exit(130)
    except Exception as e:
        print(f"❌ 等温线绘制过程中出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
