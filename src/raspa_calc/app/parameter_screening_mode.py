import os
import sys

from raspa_calc.app import parameter_screening
from raspa_calc.runtime import config as config_module


def run_parameter_screening():
    """Run parameter screening."""
    try:
        if config_module.config is None:
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

            if "cache_dir" in calc_config and calc_config["cache_dir"]:
                os.environ["RASPA_CACHE_DIR"] = calc_config["cache_dir"]

            raspa_ver = env_config.get("raspa_version", "raspa2").lower()
            os.environ["RASPA_VERSION"] = raspa_ver
            if raspa_ver == "raspa3":
                cif_path = env_config.get("raspa3_cif_base_path", "")
            else:
                cif_path = env_config.get("raspa2_cif_dir", "")
            if cif_path:
                os.environ["RASPA_CIF_DIR"] = cif_path

        result = parameter_screening.main()
        if result:
            sys.exit(result)
    except Exception as e:
        print(f"运行参数筛选模式时出错: {str(e)}")
        sys.exit(1)


def run_auto_sh():
    """Compatibility alias for older imports."""
    run_parameter_screening()
