#!/bin/bash

set -euo pipefail

load_node_priorities() {
  if [ -n "${RASPA_NODE_PRIORITIES:-}" ]; then
    return 0
  fi
  local config_file
  config_file="$(pwd -P)/.raspa_config.yaml"
  if [ ! -f "$config_file" ]; then
    echo "提示: 未找到 .raspa_config.yaml，节点优先级未设置。如需指定节点分配顺序，请在任务目录下的 .raspa_config.yaml 中配置 node_priorities。" >&2
    RASPA_NODE_PRIORITIES=""
    export RASPA_NODE_PRIORITIES
    return 0
  fi
  RASPA_NODE_PRIORITIES=$(CONFIG_FILE="$config_file" python - <<'PY' 2>/dev/null || true
import os

path = os.environ.get("CONFIG_FILE", "")

def parse_yaml(path):
    try:
        import yaml
    except Exception:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        calc = data.get("calculation") or {}
        env = data.get("environment") or {}
        np = calc.get("node_priorities") or env.get("node_priorities") or {}
        if isinstance(np, dict):
            return {str(k): int(v) for k, v in np.items() if str(k)}
    except Exception:
        return {}
    return {}

def parse_simple(path):
    pr = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return pr
    inside = False
    indent = None
    for line in lines:
        if "node_priorities:" in line and not line.lstrip().startswith("#"):
            inside = True
            indent = len(line) - len(line.lstrip())
            continue
        if not inside:
            continue
        cur_indent = len(line) - len(line.lstrip())
        if cur_indent <= indent:
            break
        if ":" not in line:
            continue
        try:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key and val:
                pr[key] = int(val)
        except Exception:
            continue
    return pr

prio = parse_yaml(path) or parse_simple(path)
if prio:
    print(",".join(f"{k}:{v}" for k, v in prio.items()))
PY
  )
  if [ -z "${RASPA_NODE_PRIORITIES:-}" ]; then
    echo "提示: .raspa_config.yaml 中未找到 node_priorities 配置，节点优先级未设置。" >&2
  fi
  export RASPA_NODE_PRIORITIES
}
