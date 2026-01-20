get_space_policy() {
  python3 - <<'PY' 2>/dev/null || true
import os

paths = [
    os.path.join(os.getcwd(), "config.yaml"),
    os.path.join(os.getcwd(), ".raspa_tools", "config.yaml"),
    os.path.expanduser("~/raspa2-calc/.raspa_tools/config.yaml"),
]

def parse_simple(path):
    min_gb = None
    action = None
    try:
        lines = open(path, "r", encoding="utf-8").read().splitlines()
    except Exception:
        return None, None
    inside = False
    indent = None
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        if line.strip() == "environment:":
            inside = True
            indent = len(line) - len(line.lstrip())
            continue
        if not inside:
            continue
        cur = len(line) - len(line.lstrip())
        if cur <= (indent or 0) and line.strip():
            break
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "work_dir_min_free_gb":
            min_gb = val
        elif key == "work_dir_min_free_action":
            action = val
    return min_gb, action

def parse_yaml(path):
    try:
        import yaml  # type: ignore
    except Exception:
        return None, None
    try:
        data = yaml.safe_load(open(path, "r", encoding="utf-8")) or {}
    except Exception:
        return None, None
    env = data.get("environment") or {}
    return env.get("work_dir_min_free_gb"), env.get("work_dir_min_free_action")

min_gb = None
action = None
for p in paths:
    if not os.path.exists(p):
        continue
    min_gb, action = parse_yaml(p)
    if min_gb is None and action is None:
        min_gb, action = parse_simple(p)
    if min_gb is not None or action is not None:
        break

if min_gb is None:
    min_gb = ""
if action is None:
    action = ""
print(f"{min_gb} {action}".strip())
PY
}

check_disk_space() {
  local work_path="$1"
  [ -z "$work_path" ] && return 0

  local min_free_gb="${RASPA_MIN_FREE_GB:-}"
  local action="${RASPA_MIN_FREE_ACTION:-}"
  if [ -z "$min_free_gb" ] || [ -z "$action" ]; then
    local policy
    policy="$(get_space_policy)"
    if [ -z "$min_free_gb" ] && [ -n "$policy" ]; then
      min_free_gb="$(printf "%s" "$policy" | awk '{print $1}')"
    fi
    if [ -z "$action" ] && [ -n "$policy" ]; then
      action="$(printf "%s" "$policy" | awk '{print $2}')"
    fi
  fi

  if [ -z "$min_free_gb" ]; then
    min_free_gb=50
  fi
  if ! [[ "$min_free_gb" =~ ^[0-9]+$ ]]; then
    min_free_gb=50
  fi
  action="$(printf "%s" "${action:-warn}" | tr '[:upper:]' '[:lower:]')"
  if ! [[ "$action" =~ ^(warn|abort)$ ]]; then
    action="warn"
  fi

  local free_gb
  free_gb=$(python3 - <<'PY' "$work_path" 2>/dev/null || true
import shutil
import sys

path = sys.argv[1]
try:
    usage = shutil.disk_usage(path)
    free_gb = int(usage.free / (1024 ** 3))
    print(free_gb)
except Exception:
    pass
PY
  )
  [ -z "$free_gb" ] && return 0

  if [ "$free_gb" -lt "$min_free_gb" ]; then
    echo "⚠️  磁盘空间不足: ${work_path}"
    echo "   当前剩余: ${free_gb} GB，安全阈值: ${min_free_gb} GB"
    if [ "$action" = "abort" ]; then
      echo "❌ 空间不足，已阻断提交。"
      exit 1
    fi
  fi
}
