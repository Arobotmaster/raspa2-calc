#!/usr/bin/env python3
"""
Lightweight SLURM cluster info CLI.

Outputs JSON compatible with task_runner.get_slurm_cluster_resources()
to keep resource probing logic in one place.

Usage:
  python cluster_info.py            # prints JSON to stdout
"""
import json
import os
import sys

# Make task_runner importable
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from task_runner import get_slurm_cluster_resources  # type: ignore
except Exception as exc:
    # Fallback: no task_runner available
    print(json.dumps({
        "available": False,
        "error": f"import_error: {exc}"
    }))
    sys.exit(0)


def main() -> int:
    try:
        info = get_slurm_cluster_resources()
        # Ensure JSON-serializable (floats/ints/None are fine)
        print(json.dumps(info, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({
            "available": False,
            "error": f"probe_error: {exc}"
        }))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

