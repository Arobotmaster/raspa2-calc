"""CLI entrypoint for the CSV/CIF filter."""

import sys

from raspa_calc.app import ciffilter


def _print_help() -> None:
    print("RASPA CSV/CIF filtering tool")
    print("Usage: python -m raspa_calc.entrypoints.ciffilter")
    print("Parameters:")
    print("  (none) interactive prompts only")


def main() -> int:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        _print_help()
        return 0
    return ciffilter.main()


if __name__ == "__main__":
    raise SystemExit(main())
