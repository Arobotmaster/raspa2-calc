"""CLI entrypoint for data extraction."""

import sys

from raspa_calc.app import data_extractor


def _print_help() -> None:
    print("RASPA data extraction tool")
    print("Usage: python -m raspa_calc.entrypoints.data_extractor")
    print("Parameters:")
    print("  (none) interactive prompts only")


def main() -> int:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        _print_help()
        return 0
    return data_extractor.main()


if __name__ == "__main__":
    raise SystemExit(main())
