"""CLI entrypoint for isotherm plotting."""

import sys

from raspa_calc.app import isotherm_plotter


def _print_help() -> None:
    print("RASPA isotherm plotting tool")
    print("Usage: python -m raspa_calc.entrypoints.isotherm_plotter [options]")
    print("Options:")
    print("  --base-dir PATH          base directory to scan (default: CWD)")
    print("  --component NAME         component name to plot")
    print("  --type {absolute,excess} adsorption type")
    print("  --unit {mol/kg,cm^3/g,mg/g,cm^3/cm^3} loading unit")
    print("  --pressure-unit {Pa,bar} pressure unit for x-axis")
    print("  --logx                   use log scale for x-axis")
    print("  --linearx                force linear x-axis")
    print("  --outdir PATH            output directory")
    print("  --combine-all            also plot combined isotherms")
    print("  --include-unfinished     include unfinished simulations")


def main() -> int:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        _print_help()
        return 0
    return isotherm_plotter.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
