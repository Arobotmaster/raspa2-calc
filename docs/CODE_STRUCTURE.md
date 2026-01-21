# Code Structure Overview

This document summarizes the current file layout and how the main modes are
wired together. It is intended as a quick reference for maintainers.

## Top-Level Layout

```
.raspa_tools/
  bin/                         # CLI shims (raspa-calc, raspa-status, ...)
  scripts/
    python/
      raspa_calc.py            # Entry point for raspa-calc CLI
      raspa_calc/              # Core package (config/env/menu/modes/tools)
      task_runner.py           # Entry point for high-throughput runner
      task_runner/             # Compatibility shim package
      common/                  # Compatibility shim package
      parameter_screening.py   # Compatibility shim for tools.parameter_screening
      data_extractor.py        # Compatibility shim for tools.data_extractor
      data_extractor_raspa3.py  # Compatibility shim for tools.data_extractor_raspa3
      warning_processor.py     # Compatibility shim for tools.warning_processor
      isotherm_plotter.py      # Compatibility shim for tools.isotherm_plotter
      ciffilter.py             # Compatibility shim for tools.ciffilter
      clean_cif_labels.py      # Compatibility shim for tools.clean_cif_labels
      force_field_utils.py     # Compatibility shim for tools.force_field_utils
    shell/                     # Shell workflows (auto.sh, simulate_workflow.sh)
  job_templates/               # Scheduler templates (SLURM/PBS/local)
  config.yaml                  # Default runtime configuration
  raspa3json/                  # RASPA3 templates and molecule definitions
  raspa2-3/                    # RASPA2/3 conversion helpers
  docs/                        # Documentation
```

## Core Package (`scripts/python/raspa_calc/`)

```
raspa_calc/
  cli.py                       # Main CLI, shows menu and dispatches modes
  menu.py                      # Help/version text and mode descriptions
  config.py                    # Loads config.yaml via common.config
  env_check.py                 # Environment validation
  modes/                       # Mode entrypoints (user-facing)
    parameter_screening.py
    high_throughput.py
    data_extractor.py
    warning_processor.py
    isotherm_plotter.py
    ciffilter.py
  tools/                       # Implementation modules
    parameter_screening.py
    data_extractor.py
    data_extractor_raspa3.py
    warning_processor.py
    isotherm_plotter.py
    ciffilter.py
    clean_cif_labels.py
    force_field_utils.py
  task_runner/                 # High-throughput engine (cli/scheduler/etc.)
    cli.py
    scheduler.py
    framework.py
    inputs.py
    templates.py
    env.py
    logging_utils.py
    state.py
    cif.py
  common/                      # Shared config helpers
    config.py
  algorithms/                  # Core algorithms and generators
    calculate_params.py
    raspa3_generator.py
    auto_mser_raspa2.py
    auto_mser_raspa3.py
    cluster_info.py
```

## Mode Mapping (Menu -> Module)

1) Parameter Screening  
   - `raspa_calc.modes.parameter_screening` -> `scripts/shell/auto.sh` ->
     `raspa_calc.tools.parameter_screening`

2) High-Throughput Calculation  
   - `raspa_calc.modes.high_throughput` -> `raspa_calc.task_runner.cli`

3) Data Extraction  
   - `raspa_calc.modes.data_extractor` -> `raspa_calc.tools.data_extractor`
   - RASPA3 parser: `raspa_calc.tools.data_extractor_raspa3`

4) Warning Processing  
   - `raspa_calc.modes.warning_processor` -> `raspa_calc.tools.warning_processor`

5) Isotherm Plotting  
   - `raspa_calc.modes.isotherm_plotter` -> `raspa_calc.tools.isotherm_plotter`

6) CSV/CIF Filtering  
   - `raspa_calc.modes.ciffilter` -> `raspa_calc.tools.ciffilter`

## Compatibility Shims

The top-level Python files under `scripts/python/` are thin shims that forward
to `raspa_calc.tools.*`. They are kept to preserve existing entrypoints such as:

- `python scripts/python/data_extractor.py`
- `python scripts/python/parameter_screening.py`
- `python scripts/python/clean_cif_labels.py`

The `scripts/python/task_runner/` and `scripts/python/common/` directories are
shim packages that forward to `raspa_calc.task_runner` and `raspa_calc.common`.
