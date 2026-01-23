import os
from typing import List, Optional, Tuple

try:
    import yaml  # type: ignore
    HAS_YAML = True
except Exception:
    yaml = None
    HAS_YAML = False


def tool_dir() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    cur = here
    for _ in range(6):
        if os.path.isfile(os.path.join(cur, "config.yaml")) or os.path.isfile(os.path.join(cur, "pyproject.toml")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _dedupe(paths: List[str]) -> List[str]:
    seen = set()
    ordered = []
    for path in paths:
        if not path:
            continue
        norm = _normalize_path(path)
        if norm in seen:
            continue
        seen.add(norm)
        ordered.append(norm)
    return ordered


def default_search_paths(start_dir: Optional[str] = None) -> List[str]:
    base = _normalize_path(start_dir or os.getcwd())
    paths = [
        os.path.join(tool_dir(), "config.yaml"),
        os.path.join(base, ".raspa_tools", "config.yaml"),
        os.path.join(base, "config.yaml"),
        os.path.expanduser("~/raspa2-calc/.raspa_tools/config.yaml"),
    ]
    return _dedupe(paths)


def search_paths_upward(start_dir: Optional[str] = None) -> List[str]:
    paths = []
    cur = _normalize_path(start_dir or os.getcwd())
    while True:
        paths.append(os.path.join(cur, ".raspa_tools", "config.yaml"))
        paths.append(os.path.join(cur, "config.yaml"))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    paths.append(os.path.join(tool_dir(), "config.yaml"))
    return _dedupe(paths)


def resolve_config_paths(
    config_path: Optional[str] = None,
    search_mode: str = "default",
    start_dir: Optional[str] = None,
) -> List[str]:
    if config_path:
        return _dedupe([config_path])
    if search_mode == "upward":
        return search_paths_upward(start_dir)
    return default_search_paths(start_dir)


def load_config(
    config_path: Optional[str] = None,
    search_mode: str = "default",
    start_dir: Optional[str] = None,
) -> Tuple[dict, Optional[str]]:
    if not HAS_YAML:
        return {}, None
    for path in resolve_config_paths(config_path, search_mode, start_dir):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}, path
        except Exception:
            continue
    return {}, None


def load_config_file(config_path: str) -> dict:
    if not HAS_YAML:
        raise ImportError("PyYAML is required to load config.yaml")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
