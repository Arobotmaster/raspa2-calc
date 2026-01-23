import os

from raspa_calc.common import config as common_config

# Version info
__version__ = "2.5.0"
__version_name__ = "RASPA2/RASPA3 双版本支持"

# Global config
config = None


def load_config():
    """Load config file."""
    global config
    if not common_config.HAS_YAML:
        config = {}
        print("⚠️  PyYAML未安装，使用默认设置")
        return

    config, config_path = common_config.load_config()
    if config_path:
        print(f"✅ 配置文件已加载: {config_path}")
    else:
        config = {}
        print("ℹ️  未找到配置文件，使用默认设置")


def get_raspa_version():
    """Get configured RASPA version."""
    if config:
        version = config.get("environment", {}).get("raspa_version", "raspa2")
        return version.lower() if version else "raspa2"
    return "raspa2"


def _get_work_dir():
    env_work_dir = os.environ.get("RASPA_WORK_DIR")
    if env_work_dir:
        return env_work_dir
    if config:
        env_cfg = config.get("environment", {}) or {}
        return env_cfg.get("work_dir")
    return None
