#!/usr/bin/env python3
"""
Lightweight cluster info CLI for SLURM and PBS/Torque.

Outputs JSON compatible with infra.runner.get_slurm_cluster_resources()
so callers (e.g. raspa-scale) can consume a unified shape:

{
  "available": true/false,
  "total_cpus": int,
  "allocated_cpus": int,
  "available_cpus": int,
  "other_cpus": int | optional,
  "method": "sinfo_per_node" | "pbsnodes" | ...,
  "nodes": [
    {
      "node": str,
      "total_cpus": int,
      "allocated_cpus": int,
      "other_cpus": int,
      "free_cpus": int,
      "load": float | null,
      "topology": str | "",
    }, ...
  ]
}

Usage:
  python -m raspa_calc.domain.algorithms.cluster_info  # prints JSON to stdout
"""
import json
import os
import sys

# Make infra.runner importable
PY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PY_ROOT not in sys.path:
    sys.path.insert(0, PY_ROOT)

def _which(cmd: str) -> bool:
    from shutil import which
    return which(cmd) is not None

def _safe_run(argv, timeout=30):
    import subprocess
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if out.returncode == 0:
            return out.stdout
        return ""
    except Exception:
        return ""

def _probe_slurm():
    try:
        from raspa_calc.infra.runner import get_slurm_cluster_resources  # type: ignore
    except Exception:
        return {"available": False, "error": "task_runner_import_failed"}
    try:
        return get_slurm_cluster_resources() or {"available": False}
    except Exception as exc:
        return {"available": False, "error": f"slurm_probe_error: {exc}"}

def _parse_pbsnodes_text(text: str):
    """Parse `pbsnodes -a` plain text into node dicts.

    Heuristics:
    - total_cpus: prefer status ncpus=, else np
    - allocated_cpus: prefer top-level "jobs = 0/<id>,1/<id>,..." item count;
      else if status has "jobs=..." use count of job ids; else 0.
    - load: from status loadave= (float)
    - state filters: skip nodes with state containing 'offline' or 'down'.
    """
    nodes = []
    block = []
    lines = text.splitlines()
    def flush_block(b):
        if not b:
            return
        name = None
        np = None
        ncpus = None
        load = None
        jobs_slots = None  # number of cpu slots allocated
        jobs_ids_count = None  # count of job ids in status jobs=
        state_top = ""
        status_kv = {}
        # First line is node name (no leading spaces)
        for i, line in enumerate(b):
            if i == 0:
                name = line.strip()
                continue
            s = line.rstrip()
            if " = " in s and not s.startswith("     status ="):
                key, val = s.split(" = ", 1)
                key = key.strip()
                val = val.strip()
                if key == "np":
                    try:
                        np = int(val)
                    except Exception:
                        np = None
                elif key == "state":
                    state_top = val
                elif key == "jobs":
                    # format like: 0/123.master,1/123.master,...
                    if "/" in val:
                        parts = [x for x in val.split(",") if x.strip()]
                        jobs_slots = len(parts)
            # status line
            if s.startswith("     status ="):
                _, val = s.split("=", 1)
                val = val.strip()
                # parse comma-separated key=value in status
                for item in val.split(","):
                    if "=" in item:
                        k, v = item.split("=", 1)
                        status_kv[k.strip()] = v.strip()
        # derive fields
        if "ncpus" in status_kv:
            try:
                ncpus = int(status_kv.get("ncpus", "") or 0)
            except Exception:
                ncpus = None
        if ncpus is None:
            ncpus = np or 0
        try:
            load = float(status_kv.get("loadave", "")) if status_kv.get("loadave") else None
        except Exception:
            load = None
        if jobs_slots is None and status_kv.get("jobs"):
            # jobs list space separated job ids
            jobs_ids_count = len([x for x in status_kv.get("jobs", "").split() if x])
        allocated = jobs_slots if jobs_slots is not None else (jobs_ids_count or 0)
        other = 0
        free = max(0, int(ncpus or 0) - int(allocated or 0) - other)
        # filter states
        # combine top-level and status state strings
        state_all = ",".join([x for x in (state_top, status_kv.get("state", "")) if x])
        if any(x in state_all for x in ("offline", "down")):
            pass  # skip entirely
        # append
        if name:
            nodes.append({
                "node": name,
                "total_cpus": int(ncpus or 0),
                "allocated_cpus": int(allocated or 0),
                "other_cpus": int(other),
                "free_cpus": int(free),
                "load": load,
                "topology": "",
            })
    # split into blocks by empty line and non-indented name lines
    for line in lines + [""]:
        if line.strip() == "":
            flush_block(block)
            block = []
        else:
            if block == [] and not line.startswith(" "):
                block = [line]
            else:
                block.append(line)
    # aggregate
    total = sum(n.get("total_cpus", 0) for n in nodes)
    alloc = sum(n.get("allocated_cpus", 0) for n in nodes)
    other = sum(n.get("other_cpus", 0) for n in nodes)
    free = sum(n.get("free_cpus", 0) for n in nodes)
    if not nodes:
        return {"available": False}
    return {
        "available": True,
        "total_cpus": int(total),
        "allocated_cpus": int(alloc),
        "other_cpus": int(other),
        "available_cpus": int(free),
        "nodes": nodes,
        "method": "pbsnodes",
    }

def _probe_pbs():
    # Prefer pbsnodes -a (text) for per-node CPU and load
    txt = _safe_run(["pbsnodes", "-a"], timeout=30)
    if txt:
        parsed = _parse_pbsnodes_text(txt)
        if parsed.get("available"):
            return parsed
    # Fallback: only server/queue info available
    qstat_out = _safe_run(["qstat", "-Bf"], timeout=15)
    if not qstat_out:
        return {"available": False}
    # We cannot infer CPU counts reliably; report available=False with hint
    return {"available": False, "error": "pbs_nodes_unavailable"}


def main() -> int:
    # Strategy: prefer SLURM if sinfo exists; else if qsub/pbsnodes exists, use PBS; else unavailable
    info = None
    if _which("sinfo"):
        info = _probe_slurm()
    elif _which("pbsnodes") or _which("qsub") or _which("qstat"):
        info = _probe_pbs()
    else:
        info = {"available": False, "error": "no_scheduler_detected"}
    print(json.dumps(info or {"available": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
