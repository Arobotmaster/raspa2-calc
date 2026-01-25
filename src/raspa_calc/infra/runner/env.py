import os


def get_raspa_version_from_env():
    """Get RASPA version from env."""
    return os.environ.get("RASPA_VERSION", "raspa2").lower()


def load_raspa3_config():
    """Load RASPA3 config from env."""
    return {
        "conda_env": os.environ.get("RASPA3_CONDA_ENV", "raspa3"),
        "json_dir": os.environ.get("RASPA3_JSON_DIR", ""),
        "cif_base_path": os.environ.get("RASPA3_CIF_BASE_PATH", ""),
        "template_path": os.environ.get("RASPA3_TEMPLATE_PATH", ""),
    }


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _positive_int(raw, default):
    try:
        value = int(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default
