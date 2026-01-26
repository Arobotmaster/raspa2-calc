# Code Structure Overview

This document summarizes the current file layout and how the main modes are
wired together. It is intended as a quick reference for maintainers.

## Top-Level Layout

```
raspa2-calc/
  README.md                   # Main user guide
  AGENTS.md                   # Repo guidelines for contributors
  CLAUDE.md                   # Notes for assistant tooling
  pyproject.toml              # Python package metadata + console scripts
  requirements.txt            # Base env pip deps
  environment.yml             # pymser env definition
  config.yaml                 # Default runtime configuration
  install.sh                  # Installer (copies repo to ~/.raspa_tools and runs pip -e)
  qdel.sh                     # Queue helper (shell)
  src/
    raspa_calc/               # Core Python package (src layout)
  bin/                        # CLI shims (raspa-calc, raspa-status, ...)
  scripts/
    shell/                    # Shell workflows (entrypoints/workers/templates/lib)
      entrypoints/            # submit.sh / scale.sh entry scripts
      workers/                # runjobs*.sh worker scripts
      templates/              # Scheduler templates root
        schedulers/           # SLURM/PBS/local templates (stable path)
      lib/                    # Shared shell helpers (scale/, disk.sh)
  raspa3json/                 # RASPA3 templates and molecule definitions
  raspa2-3/                   # RASPA2/3 conversion helpers
  nfs/                        # NFS helper scripts
  docs/                       # Documentation (including this file)
  figure/                     # Doc assets
```

## Core Package (`src/raspa_calc/`)

```
raspa_calc/
  __main__.py                 # python -m raspa_calc entry
  entrypoints/                # CLI entrypoints + menu
    interactive.py            # Main menu + mode dispatch
    menu.py                   # Help/version output
    task_runner.py            # High-throughput runner CLI
    parameter_screening.py    # Parameter screening CLI
    data_extractor.py         # Data extraction CLI
    warning_processor.py      # Warning processor CLI
    isotherm_plotter.py       # Isotherm plotting CLI
    ciffilter.py              # CSV/CIF filter CLI
  app/                        # Use cases and workflows
    task_runner.py
    high_throughput.py
    parameter_screening.py
    parameter_screening_mode.py
    data_extractor.py
    data_extractor_mode.py
    warning_processor.py
    warning_processor_mode.py
    isotherm_plotter.py
    isotherm_plotter_mode.py
    ciffilter.py
    ciffilter_mode.py
  runtime/                    # Config/env/diagnostics
    config.py
    diagnostics.py
  infra/                      # Scheduler + external integrations
    job_scripts.py
    runner/
      scheduler.py
      framework.py
      inputs.py
      templates.py
      env.py
      logging_utils.py
      state.py
      cif.py
      csv_utils.py
      submit_utils.py
      void_utils.py
  domain/                     # Algorithms and parsers
    algorithms/
      calculate_params.py
      raspa3_generator.py
      raspa3_io.py
      auto_mser_raspa2.py
      auto_mser_raspa3.py
      cluster_info.py
    parsers/
      data_extractor_raspa3.py
    utils/
      clean_cif_labels.py
      force_field_utils.py
```

## Mode Mapping (Menu -> Module)

1) Parameter Screening  
   - `raspa_calc.entrypoints.interactive` -> `raspa_calc.app.parameter_screening_mode`
   - `raspa_calc.app.parameter_screening_mode` -> `raspa_calc.app.parameter_screening`

2) High-Throughput Calculation  
   - `raspa_calc.entrypoints.interactive` -> `raspa_calc.app.high_throughput` ->
     `raspa_calc.entrypoints.task_runner`

3) Data Extraction  
   - `raspa_calc.entrypoints.interactive` -> `raspa_calc.app.data_extractor_mode` ->
     `raspa_calc.entrypoints.data_extractor`
   - RASPA3 parser: `raspa_calc.domain.parsers.data_extractor_raspa3`

4) Warning Processing  
   - `raspa_calc.entrypoints.interactive` -> `raspa_calc.app.warning_processor_mode` ->
     `raspa_calc.entrypoints.warning_processor`

5) Isotherm Plotting  
   - `raspa_calc.entrypoints.interactive` -> `raspa_calc.app.isotherm_plotter_mode` ->
     `raspa_calc.entrypoints.isotherm_plotter`

6) CSV/CIF Filtering  
   - `raspa_calc.entrypoints.interactive` -> `raspa_calc.app.ciffilter_mode` ->
     `raspa_calc.entrypoints.ciffilter`

## Python Entry Points

- `python -m raspa_calc` → main interactive menu
- `python -m raspa_calc.entrypoints.task_runner` → high-throughput runner CLI
- `python -m raspa_calc.entrypoints.data_extractor` → RASPA2/3 data extraction
- `python -m raspa_calc.entrypoints.parameter_screening` → parameter screening
- `python -m raspa_calc.entrypoints.warning_processor` → warning processing
- `python -m raspa_calc.entrypoints.isotherm_plotter` → isotherm plotting
- `python -m raspa_calc.entrypoints.ciffilter` → CSV/CIF filtering

## Shell Workflows and Templates

- `scripts/shell/entrypoints/submit.sh` and `scripts/shell/entrypoints/scale.sh`
  provide submission/scale entrypoints for CLI modes and `raspa-scale`.
- `scripts/shell/workers/` contains worker scripts (`runjobs*.sh`) that claim tasks.
- `scripts/shell/templates/schedulers/` is the stable path for scheduler templates.
  Scripts resolve it via `RASPA_TOOL_DIR/scripts/shell/templates/schedulers` (and do not
  copy templates into the work directory).
