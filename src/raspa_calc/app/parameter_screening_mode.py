import os
import sys

from raspa_calc.app import parameter_screening
from raspa_calc.runtime import config as config_module


def run_parameter_screening(config_path=None):
    """Run parameter screening."""
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

            if "cache_dir" in calc_config and calc_config["cache_dir"]:
                os.environ["RASPA_CACHE_DIR"] = calc_config["cache_dir"]

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

            allowed_nodes_cfg = (
                calc_config.get("allowed_nodes")
                or env_config.get("allowed_nodes")
                or calc_config.get("node_allowlist")
                or env_config.get("node_allowlist")
            )
            allowed_parts = []
            if isinstance(allowed_nodes_cfg, str):
                allowed_parts = [item.strip() for item in allowed_nodes_cfg.split(",") if item.strip()]
            elif isinstance(allowed_nodes_cfg, (list, tuple)):
                allowed_parts = [str(item).strip() for item in allowed_nodes_cfg if str(item).strip()]
            if allowed_parts:
                os.environ["RASPA_ALLOWED_NODES"] = ",".join(dict.fromkeys(allowed_parts))

            if "unit_cells_cutoff_scale" in calc_config:
                os.environ["RASPA_UNITCELLS_CUTOFF_SCALE"] = str(calc_config["unit_cells_cutoff_scale"])
            else:
                os.environ.pop("RASPA_UNITCELLS_CUTOFF_SCALE", None)

            if "unit_cells_edge_only" in calc_config:
                os.environ["RASPA_UNITCELLS_EDGE_ONLY"] = str(calc_config["unit_cells_edge_only"]).lower()
            else:
                os.environ.pop("RASPA_UNITCELLS_EDGE_ONLY", None)

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
