build_node_plan() {
  local limit="$1"
  local priorities="$2"
  local py_json="$3"
  local mode="$4"

  NODE_PLAN_LIMIT="$limit" PRIORITIES="$priorities" PY_JSON="$py_json" PLAN_MODE="$mode" python - <<'PY' 2>/dev/null || true
import os, json, math

def parse_prio(raw):
    pr = {}
    if not raw:
        return pr
    for part in raw.split(','):
        if ':' not in part:
            continue
        name, val = part.split(':', 1)
        name = name.strip()
        try:
            pr[name] = int(val.strip())
        except Exception:
            continue
    return pr

data = os.environ.get("PY_JSON", "")
limit = int(os.environ.get("NODE_PLAN_LIMIT", "0") or 0)
prio = parse_prio(os.environ.get("PRIORITIES", ""))
if not data or limit <= 0:
    raise SystemExit
info = json.loads(data)
nodes = info.get("nodes") or []
if not nodes:
    raise SystemExit

def node_priority(n):
    return prio.get(n.get("node"), 0)

mode = os.environ.get("PLAN_MODE", "idle").strip().lower()
if mode in ("full", "total", "all", "max"):
    mode = "full"
elif mode in ("idle", "free", "available"):
    mode = "idle"
else:
    mode = "idle"

if mode == "full":
    ordered_nodes = []
    for n in nodes:
        total = int(n.get("total_cpus", 0) or 0)
        if total <= 0:
            continue
        n["_total_cpus"] = total
        ordered_nodes.append(n)
    ordered_nodes = sorted(
        ordered_nodes,
        key=lambda n: (
            -node_priority(n),
            -(n.get("_total_cpus", 0) or 0),
            n.get("node") or "",
        ),
    )
    queue = []
    remaining = limit
    for n in ordered_nodes:
        if remaining <= 0:
            break
        cap = int(n.get("_total_cpus", 0) or 0)
        if cap <= 0:
            continue
        take = cap if cap < remaining else remaining
        queue.extend([n["node"]] * take)
        remaining -= take
    counts = {}
    for n in queue:
        counts[n] = counts.get(n, 0) + 1
    plan = ",".join(f"{k}:{v}" for k, v in counts.items() if v > 0)
    if plan:
        print(plan)
    raise SystemExit

ordered_nodes = []
assigned = {}
for n in nodes:
    total = int(n.get("total_cpus", 0) or 0)
    free = max(0, int(n.get("free_cpus", 0) or 0))
    alloc = max(0, int(n.get("allocated_cpus", 0) or 0))
    load_val_raw = n.get("load")
    try:
        load_val = float(str(load_val_raw).rstrip("*"))
    except Exception:
        load_val = None
    busy = max(alloc, load_val if load_val is not None else 0)
    headroom = max(0, total - math.ceil(busy))
    effective = max(0, min(free, headroom))
    load_ratio = 0.0
    if total > 0 and load_val is not None:
        load_ratio = max(0.0, float(load_val) / float(total))
    alloc_ratio = float(alloc) / float(total) if total > 0 else 0.0
    if load_ratio >= 0.85 or alloc_ratio >= 0.95:
        effective = 0
    elif load_ratio >= 0.70 or alloc_ratio >= 0.85:
        effective = int(effective * 0.5)
    n["_effective_free"] = effective
    n["_load_ratio"] = load_ratio
    n["_total_cpus"] = total
    ordered_nodes.append(n)

ordered_nodes = sorted(
    ordered_nodes,
    key=lambda n: (
        -node_priority(n),
        -(n.get("_effective_free", 0) or 0),
        -(n.get("free_cpus", 0) or 0),
        n.get("load") if n.get("load") is not None else 0,
    ),
)
queue = []
remaining = limit

for n in ordered_nodes:
    if remaining <= 0:
        break
    cap = int(n.get("_effective_free", 0) or 0)
    used = assigned.get(n.get("node"), 0)
    cap = max(0, cap - used)
    if cap < 0:
        cap = 0
    if cap <= 0:
        continue
    take = cap if cap < remaining else remaining
    queue.extend([n["node"]] * take)
    assigned[n.get("node")] = used + take
    remaining -= take

if remaining > 0:
    for n in ordered_nodes:
        if remaining <= 0:
            break
        cap = int(n.get("free_cpus", 0) or 0)
        used = assigned.get(n.get("node"), 0)
        cap = max(0, cap - used)
        total = int(n.get("_total_cpus", 0) or 0)
        load_ratio = float(n.get("_load_ratio", 0.0) or 0.0)
        alloc_ratio = float(n.get("allocated_cpus", 0) or 0.0) / float(total) if total > 0 else 0.0
        if load_ratio >= 0.85 or alloc_ratio >= 0.95:
            cap = 0
        elif load_ratio >= 0.70 or alloc_ratio >= 0.85:
            cap = int(cap * 0.5)
        if cap < 0:
            cap = 0
        take = cap if cap < remaining else remaining
        if take <= 0:
            continue
        queue.extend([n["node"]] * take)
        assigned[n.get("node")] = used + take
        remaining -= take

counts = {}
for n in queue:
    counts[n] = counts.get(n, 0) + 1
plan = ",".join(f"{k}:{v}" for k, v in counts.items() if v > 0)
if plan:
    print(plan)
PY
}
