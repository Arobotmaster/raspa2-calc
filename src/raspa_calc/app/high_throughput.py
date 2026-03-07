import os
import sys

from raspa_calc.runtime import config as config_module


def run_high_throughput(config_path=None):
    """Run high-throughput task runner."""
    try:
        if config_path:
            os.environ["RASPA_CONFIG"] = os.path.abspath(os.path.expanduser(config_path))
            config_module.load_runtime_config(config_path=os.environ["RASPA_CONFIG"])
        elif config_module.config is None:
            config_module.load_runtime_config()

        if config_module.config:
            env_config = config_module.config.get("environment", {})
            calc_config = config_module.config.get("calculation", {})

            work_dir_cfg = env_config.get("work_dir") or os.environ.get("RASPA_WORK_DIR")
            if work_dir_cfg:
                os.environ["RASPA_WORK_DIR"] = work_dir_cfg
                try:
                    os.chdir(work_dir_cfg)
                except FileNotFoundError:
                    print(f"❌ 工作目录不存在: {work_dir_cfg}")
                    sys.exit(1)
            else:
                os.environ["RASPA_WORK_DIR"] = os.getcwd()

            raspa_ver = env_config.get("raspa_version", "raspa2").lower()
            if raspa_ver == "raspa3":
                cif_path = env_config.get("raspa3_cif_base_path", "")
            else:
                cif_path = env_config.get("raspa2_cif_dir", "")

            if cif_path:
                os.environ["RASPA_CIF_DIR"] = cif_path

            if "cutoff_radius" in calc_config:
                os.environ["RASPA_CUTOFF_RADIUS"] = str(calc_config["cutoff_radius"])

            if "default_molecules" in calc_config:
                os.environ["RASPA_DEFAULT_MOLECULES"] = calc_config["default_molecules"]

            if "output_directory" in calc_config:
                os.environ["RASPA_OUTPUT_DIR"] = calc_config["output_directory"]

            try:
                out_dir_name = calc_config.get("output_directory")
                base_dir = os.environ.get("RASPA_WORK_DIR", os.getcwd())
                if out_dir_name and base_dir:
                    snap_dir = os.path.join(base_dir, out_dir_name)
                    os.makedirs(snap_dir, exist_ok=True)
                    snap_path = os.path.join(snap_dir, ".raspa_config.yaml")
                    try:
                        import yaml  # type: ignore
                        with open(snap_path, "w", encoding="utf-8") as fh:
                            yaml.safe_dump(config_module.config or {}, fh, allow_unicode=True)
                    except Exception:
                        import json
                        with open(snap_path, "w", encoding="utf-8") as fh:
                            fh.write(json.dumps(config_module.config or {}, ensure_ascii=False, indent=2))
                    print(f"ℹ️  当前配置已保存: {snap_path}")
            except Exception as save_err:
                print(f"⚠️  保存配置快照失败: {save_err}")

            mser_config = calc_config.get("mser", {})
            if mser_config:
                if "enable" in mser_config:
                    os.environ["RASPA_MSER_ENABLE"] = str(mser_config.get("enable", False)).lower()
                if "target_cycles" in mser_config:
                    os.environ["RASPA_MSER_TARGET_CYCLES"] = str(mser_config.get("target_cycles", 1000))
                if "add_cycles" in mser_config:
                    os.environ["RASPA_MSER_ADD_CYCLES"] = str(mser_config.get("add_cycles", 500))
                if "max_iter" in mser_config:
                    os.environ["RASPA_MSER_MAX_ITER"] = str(mser_config.get("max_iter", 20))
                if "uncertainty" in mser_config:
                    os.environ["RASPA_MSER_UNCERTAINTY"] = mser_config.get("uncertainty", "uSD")
                if "conda_env" in mser_config:
                    os.environ["RASPA_MSER_CONDA_ENV"] = mser_config.get("conda_env", "pymser")
                if "llm" in mser_config:
                    os.environ["RASPA_MSER_LLM"] = str(mser_config.get("llm", True)).lower()
                if "batch_size" in mser_config:
                    os.environ["RASPA_MSER_BATCH_SIZE"] = str(mser_config.get("batch_size", 5))

            raspa_version = env_config.get("raspa_version", "raspa2").lower()

            if raspa_version == "raspa3":
                if "raspa3_template_path" in env_config and env_config["raspa3_template_path"]:
                    os.environ["RASPA_TEMPLATE_PATH"] = env_config["raspa3_template_path"]
            else:
                if "template_path" in env_config and env_config["template_path"]:
                    os.environ["RASPA_TEMPLATE_PATH"] = env_config["template_path"]

            if "RASPA_NODE_PRIORITIES" not in os.environ:
                node_pri_cfg = env_config.get("node_priorities")
                if (not node_pri_cfg) and isinstance(calc_config.get("node_priorities"), dict):
                    node_pri_cfg = calc_config.get("node_priorities")
                if isinstance(node_pri_cfg, dict) and node_pri_cfg:
                    parts = []
                    for k, v in node_pri_cfg.items():
                        try:
                            parts.append(f"{k}:{int(v)}")
                        except Exception:
                            continue
                    if parts:
                        os.environ["RASPA_NODE_PRIORITIES"] = ",".join(parts)

            if "use_void_csv" in calc_config:
                os.environ["RASPA_USE_VOID_CSV"] = str(calc_config["use_void_csv"]).lower()

            if "void_csv_file" in calc_config:
                os.environ["RASPA_VOID_CSV_FILE"] = calc_config["void_csv_file"]

            if "void_column" in calc_config:
                os.environ["RASPA_VOID_COLUMN"] = calc_config["void_column"]

            if "use_cif_cache" in calc_config:
                os.environ["RASPA_USE_CIF_CACHE"] = str(calc_config["use_cif_cache"]).lower()

            if "cif_cache_path" in calc_config and calc_config["cif_cache_path"]:
                os.environ["RASPA_CIF_CACHE_PATH"] = calc_config["cif_cache_path"]

            if "cache_dir" in calc_config and calc_config["cache_dir"]:
                os.environ["RASPA_CACHE_DIR"] = calc_config["cache_dir"]

            if "csv_file_path" in calc_config and calc_config["csv_file_path"]:
                os.environ["RASPA_CSV_FILE"] = calc_config["csv_file_path"]

            if "framework_column" in calc_config:
                os.environ["RASPA_FRAMEWORK_COLUMN"] = calc_config["framework_column"]

            logging_config = config_module.config.get("logging", {})
            if "output_dir" in logging_config and logging_config["output_dir"]:
                os.environ["RASPA_JOB_LOG_DIR"] = logging_config["output_dir"]
            else:
                os.environ.pop("RASPA_JOB_LOG_DIR", None)

            if "enable_job_logs" in logging_config:
                os.environ["RASPA_ENABLE_JOB_LOGS"] = str(logging_config["enable_job_logs"]).lower()
            else:
                os.environ.pop("RASPA_ENABLE_JOB_LOGS", None)

            os.environ["RASPA_TOOL_DIR"] = os.path.expanduser("~/raspa2-calc/.raspa_tools")
            os.environ["RASPA_VERSION"] = raspa_version

            if raspa_version == "raspa3":
                if "raspa3_conda_env" in env_config:
                    os.environ["RASPA3_CONDA_ENV"] = env_config["raspa3_conda_env"]
                if "raspa3_json_dir" in env_config and env_config["raspa3_json_dir"]:
                    os.environ["RASPA3_JSON_DIR"] = env_config["raspa3_json_dir"]
                if "raspa3_cif_base_path" in env_config and env_config["raspa3_cif_base_path"]:
                    os.environ["RASPA3_CIF_BASE_PATH"] = env_config["raspa3_cif_base_path"]
                if "raspa3_template_path" in env_config and env_config["raspa3_template_path"]:
                    os.environ["RASPA3_TEMPLATE_PATH"] = env_config["raspa3_template_path"]
                print(f"✅ 已设置 RASPA3 环境变量 (Conda环境: {env_config.get('raspa3_conda_env', 'raspa3')})")

            print("✅ 已从配置文件加载计算参数")

        from raspa_calc.app.task_runner import main as task_runner_main
        task_runner_main()
    except ImportError:
        print("错误: 找不到task_runner模块")
        sys.exit(1)
    except Exception as e:
        print(f"运行高通量计算模式时出错: {str(e)}")
        sys.exit(1)


def run_task_runner():
    """Compatibility alias for older imports."""
    run_high_throughput()
