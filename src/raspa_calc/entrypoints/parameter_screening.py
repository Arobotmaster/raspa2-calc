"""CLI entrypoint for parameter screening."""

import sys

from raspa_calc.app import parameter_screening


def _print_help() -> None:
    print("RASPA parameter screening tool")
    print("Usage: python -m raspa_calc.entrypoints.parameter_screening [csv_file] [column_number]")
    print("Args:")
    print("  csv_file       CSV path")
    print("  column_number  column number with framework names")
    print("Options:")
    print("  --cif-dir PATH                 CIF directory")
    print("  --molecule NAME                molecule name")
    print("  --template PATH                simulation.input template path")
    print("  --job-system {auto,slurm,pbs,local}  scheduler type")
    print("  --config PATH                  config file path")
    print("  --use-config                   use config values only")


def main() -> int:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        _print_help()
        return 0
    return parameter_screening.main()


if __name__ == "__main__":
    raise SystemExit(main())
