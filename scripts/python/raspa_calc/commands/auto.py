import os
import sys

from .. import config as config_module


def run_auto_sh():
    """Run parameter screening (auto.sh)."""
    try:
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

        tool_dir = os.environ.get("HOME", "") + "/raspa2-calc/.raspa_tools"
        auto_sh = os.path.join(tool_dir, "scripts/shell/auto.sh")

        if not os.path.exists(auto_sh):
            print(f"错误: 找不到脚本文件 {auto_sh}")
            sys.exit(1)

        os.system(f"bash {auto_sh}")
    except Exception as e:
        print(f"运行参数筛选模式时出错: {str(e)}")
        sys.exit(1)
