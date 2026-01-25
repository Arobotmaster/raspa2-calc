ts() { date +"%Y-%m-%d %H:%M:%S,%3N"; }
node_cpu_count() { command -v nproc >/dev/null 2>&1 && nproc || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1; }

#!/bin/bash

set -euo pipefail

scan_task_counts() {
  local target="$1"
  local jobs="${RASPA_SCALE_SCAN_JOBS:-}"
  local mode="${RASPA_SCALE_SCAN_MODE:-auto}"
  local cache_sec="${RASPA_SCALE_SCAN_CACHE_SEC:-15}"
  local pattern="${RASPA_SCALE_SCAN_PATTERN:-^mc[0-9].*$}"
  local out=""
  if ! [[ "$cache_sec" =~ ^[0-9]+$ ]]; then
    cache_sec=15
  fi
  local now
  now=$(date +%s)
  if [ "$SCAN_CACHE_TARGET" = "$target" ] && [ "$SCAN_CACHE_TS" -gt 0 ] && [ "$cache_sec" -gt 0 ]; then
    if [ $((now - SCAN_CACHE_TS)) -le "$cache_sec" ]; then
      RUNNING_COUNT="$SCAN_CACHE_RUNNING"
      PENDING_COUNT="$SCAN_CACHE_PENDING"
      return 0
    fi
  fi

  local jobs_disp
  jobs_disp="${jobs:-auto}"
  echo "$(ts) - INFO - 统计任务目录: ${target} (mode=${mode}, threads=${jobs_disp})"
  out=$(python - "$target" "${jobs:-}" "${mode:-}" "${RASPA_SCALE_SCAN_FAST_THRESHOLD:-}" "${pattern:-}" <<'PY' 2>/dev/null || true
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

target = sys.argv[1] if len(sys.argv) > 1 else ""
jobs_raw = sys.argv[2] if len(sys.argv) > 2 else ""
mode_raw = sys.argv[3] if len(sys.argv) > 3 else ""
threshold_raw = sys.argv[4] if len(sys.argv) > 4 else ""
pattern_raw = sys.argv[5] if len(sys.argv) > 5 else ""

def _parse_int(val):
    try:
        return int(val)
    except Exception:
        return None

jobs = _parse_int(jobs_raw)
if jobs is None or jobs <= 0:
    try:
        jobs = os.cpu_count() or 1
    except Exception:
        jobs = 1
    if jobs > 32:
        jobs = 32

mode = (mode_raw or "auto").strip().lower()
if mode in ("fast", "simple"):
    mode = "fast"
elif mode in ("verify", "strict"):
    mode = "verify"
else:
    mode = "auto"

threshold = _parse_int(threshold_raw)
if threshold is None or threshold <= 0:
    threshold = 2000

if not target:
    sys.exit(1)

pat = re.compile(pattern_raw or r"^mc[0-9].*$")
running = 0
pending_dirs = []
pending_candidates = 0
use_fast = mode == "fast"
task_list = os.path.join(target, ".raspa_queue", "tasks.list")

def has_sim(path):
    try:
        return (
            os.path.isfile(os.path.join(path, "simulation.input")) or
            os.path.isfile(os.path.join(path, "simulation.json"))
        )
    except Exception:
        return False

if os.path.isfile(task_list):
    try:
        with open(task_list, "r", encoding="utf-8") as fh:
            tasks = [line.rstrip("\n").strip() for line in fh if line.strip()]
    except Exception:
        tasks = []

    if not tasks:
        print("0 0")
        sys.exit(0)

    if mode == "auto" and len(tasks) >= threshold:
        use_fast = True

    def check_task(rel):
        base = os.path.join(target, rel.rstrip("/"))
        if os.path.isdir(base + "__running"):
            return (1, 0)
        if os.path.isdir(base):
            if use_fast:
                return (0, 1)
            return (0, 1 if has_sim(base) else 0)
        return (0, 0)

    if jobs <= 1 or len(tasks) < 200:
        for rel in tasks:
            r, p = check_task(rel)
            running += r
            pending_candidates += p
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            for r, p in pool.map(check_task, tasks):
                running += r
                pending_candidates += p

    print(f"{running} {pending_candidates}")
    sys.exit(0)

try:
    with os.scandir(target) as it:
        for entry in it:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except Exception:
                continue
            name = entry.name
            if name.startswith("mc") and name.endswith("__running"):
                running += 1
                continue
            if "__" in name:
                continue
            if pat.match(name):
                pending_candidates += 1
                if not use_fast:
                    pending_dirs.append(entry.path)
                    if mode == "auto" and pending_candidates >= threshold:
                        use_fast = True
                        pending_dirs = []
except Exception:
    sys.exit(1)

if use_fast:
    pending = pending_candidates
else:
    if jobs <= 1 or len(pending_dirs) < 200:
        pending = sum(1 for p in pending_dirs if has_sim(p))
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            pending = sum(1 for ok in pool.map(has_sim, pending_dirs) if ok)

print(f"{running} {pending}")
PY
  )
  if [ -n "$out" ]; then
    read -r RUNNING_COUNT PENDING_COUNT <<< "$out"
    if [[ "${RUNNING_COUNT:-}" =~ ^[0-9]+$ ]] && [[ "${PENDING_COUNT:-}" =~ ^[0-9]+$ ]]; then
      SCAN_CACHE_TARGET="$target"
      SCAN_CACHE_TS="$now"
      SCAN_CACHE_RUNNING="$RUNNING_COUNT"
      SCAN_CACHE_PENDING="$PENDING_COUNT"
      return 0
    fi
  fi
  RUNNING_COUNT=$(find "$target" -maxdepth 1 -type d -name 'mc*__running' 2>/dev/null | wc -l | awk '{print $1}')
  PENDING_COUNT=0
  while IFS= read -r d; do
    if [ -f "$d/simulation.input" ] || [ -f "$d/simulation.json" ]; then
      PENDING_COUNT=$((PENDING_COUNT+1))
    fi
  done < <(find "$target" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -printf '%p\n' 2>/dev/null)
  SCAN_CACHE_TARGET="$target"
  SCAN_CACHE_TS="$now"
  SCAN_CACHE_RUNNING="$RUNNING_COUNT"
  SCAN_CACHE_PENDING="$PENDING_COUNT"
}
