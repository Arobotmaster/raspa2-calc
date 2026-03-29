#!/bin/bash

set -euo pipefail

load_node_priorities() {
  if [ -n "${RASPA_NODE_PRIORITIES:-}" ] && [ -n "${RASPA_ALLOWED_NODES:-}" ]; then
    return 0
  fi
  local config_file
  config_file="$(pwd -P)/.raspa_config.yaml"
  if [ ! -f "$config_file" ]; then
    echo "提示: 未找到 .raspa_config.yaml，节点优先级未设置。如需指定节点分配顺序，请在任务目录下的 .raspa_config.yaml 中配置 node_priorities。" >&2
    : "${RASPA_NODE_PRIORITIES:=}"
    : "${RASPA_ALLOWED_NODES:=}"
    export RASPA_NODE_PRIORITIES RASPA_ALLOWED_NODES
    return 0
  fi
  local parsed_config
  parsed_config=$(CONFIG_FILE="$config_file" python - <<'PY' 2>/dev/null || true
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
        allowed = (
            calc.get("allowed_nodes")
            or env.get("allowed_nodes")
            or calc.get("node_allowlist")
            or env.get("node_allowlist")
            or []
        )
        pr = {}
        if isinstance(np, dict):
            pr = {str(k): int(v) for k, v in np.items() if str(k)}
        allowed_nodes = []
        if isinstance(allowed, str):
            allowed_nodes = [item.strip() for item in allowed.split(",") if item.strip()]
        elif isinstance(allowed, (list, tuple)):
            allowed_nodes = [str(item).strip() for item in allowed if str(item).strip()]
        return pr, allowed_nodes
    except Exception:
        return {}, []
    return {}, []

def parse_simple(path):
    pr = {}
    allowed = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return pr, allowed
    inside_prio = False
    prio_indent = None
    inside_allowed = False
    allowed_indent = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cur_indent = len(line) - len(line.lstrip())
        if "node_priorities:" in line:
            inside_prio = True
            prio_indent = cur_indent
            inside_allowed = False
            continue
        if "allowed_nodes:" in line or "node_allowlist:" in line:
            inside_allowed = True
            allowed_indent = cur_indent
            inside_prio = False
            inline = line.split(":", 1)[1].strip()
            if inline:
                allowed.extend([item.strip() for item in inline.split(",") if item.strip()])
            continue
        if inside_prio:
            if cur_indent <= prio_indent:
                inside_prio = False
            elif ":" in line:
                try:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if key and val:
                        pr[key] = int(val)
                except Exception:
                    pass
        if inside_allowed:
            if cur_indent <= allowed_indent:
                inside_allowed = False
            elif stripped.startswith("- "):
                item = stripped[2:].strip()
                if item:
                    allowed.append(item)
            elif ":" in stripped:
                # 进入下一个同级块
                inside_allowed = False
        if (not inside_prio) and (not inside_allowed):
            continue
    return pr, allowed

prio, allowed = parse_yaml(path)
if not prio and not allowed:
    prio, allowed = parse_simple(path)
if prio:
    print("PRIORITIES=" + ",".join(f"{k}:{v}" for k, v in prio.items()))
if allowed:
    print("ALLOWED=" + ",".join(dict.fromkeys(allowed)))
PY
  )
  local parsed_priorities=""
  local parsed_allowed=""
  while IFS= read -r line; do
    case "$line" in
      PRIORITIES=*) parsed_priorities="${line#PRIORITIES=}" ;;
      ALLOWED=*) parsed_allowed="${line#ALLOWED=}" ;;
    esac
  done <<< "$parsed_config"
  if [ -z "${RASPA_NODE_PRIORITIES:-}" ]; then
    RASPA_NODE_PRIORITIES="$parsed_priorities"
  fi
  if [ -z "${RASPA_ALLOWED_NODES:-}" ]; then
    RASPA_ALLOWED_NODES="$parsed_allowed"
  fi
  if [ -z "${RASPA_NODE_PRIORITIES:-}" ]; then
    echo "提示: .raspa_config.yaml 中未找到 node_priorities 配置，节点优先级未设置。" >&2
  fi
  export RASPA_NODE_PRIORITIES RASPA_ALLOWED_NODES
}
