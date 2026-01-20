load_node_priorities() {
  if [ -n "${RASPA_NODE_PRIORITIES:-}" ]; then
    return 0
  fi
  RASPA_NODE_PRIORITIES=$(python - <<'PY' 2>/dev/null || true
import os

search = []
pwd = os.getcwd()
search.append(os.path.join(pwd, "config.yaml"))
search.append(os.path.join(pwd, ".raspa_tools", "config.yaml"))
search.append(os.path.expanduser("~/raspa2-calc/.raspa_tools/config.yaml"))

def parse_simple(path: str):
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
        # stop if dedent
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

def parse_yaml(path: str):
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        env = data.get("environment") or {}
        calc = data.get("calculation") or {}
        np = env.get("node_priorities") or calc.get("node_priorities") or {}
        if isinstance(np, dict):
            return {str(k): int(v) for k, v in np.items() if str(k)}
    except Exception:
        return {}
    return {}

prio = {}
for path in search:
    if not os.path.exists(path):
        continue
    prio = parse_yaml(path)
    if not prio:
        prio = parse_simple(path)
    if prio:
        break

if prio:
    print(",".join(f"{k}:{v}" for k, v in prio.items()))
PY
  )
  export RASPA_NODE_PRIORITIES
}
