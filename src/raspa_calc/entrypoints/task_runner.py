"""CLI entrypoint for the task runner."""

import sys

from raspa_calc.app import task_runner


def _print_help() -> None:
    print("RASPA high-throughput task runner")
    print("Usage: python -m raspa_calc.entrypoints.task_runner [csv_file] [column_number]")
    print("Args:")
    print("  csv_file       CSV path (optional; falls back to env/config)")
    print("  column_number  column number with framework names")
    print("Environment:")
    print("  RASPA_CSV_FILE")
    print("  RASPA_FRAMEWORK_COLUMN")
    print("  RASPA_CIF_DIR")


def main() -> int:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        _print_help()
        return 0
    return task_runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
