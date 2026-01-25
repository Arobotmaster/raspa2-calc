"""CLI entrypoint for warning processing."""

import sys

from raspa_calc.app import warning_processor


def _print_help() -> None:
    print("RASPA warning processor")
    print("Usage: python -m raspa_calc.entrypoints.warning_processor")
    print("Parameters:")
    print("  (none) interactive prompts only")


def main() -> int:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        _print_help()
        return 0
    return warning_processor.main()


if __name__ == "__main__":
    raise SystemExit(main())
