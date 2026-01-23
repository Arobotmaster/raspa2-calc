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
    shell/                    # Shell workflows (auto.sh, simulate_workflow.sh)
      raspa_scale/            # raspa-scale helpers and shared libs
  job_templates/              # Scheduler templates (SLURM/PBS/local), resolved via RASPA_TOOL_DIR
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
  cli/                        # CLI entrypoints
    raspa_calc.py             # Main menu + mode dispatch
    task_runner.py            # High-throughput runner CLI
  core/                       # Config/env/menu utilities
    config.py
    env_check.py
    menu.py
  modes/                      # Mode entrypoints (user-facing)
    parameter_screening.py
    high_throughput.py
    data_extractor.py
    warning_processor.py
    isotherm_plotter.py
    ciffilter.py
  tools/                      # Implementation modules
    parameter_screening.py
    data_extractor.py
    data_extractor_raspa3.py
    warning_processor.py
    isotherm_plotter.py
    ciffilter.py
    clean_cif_labels.py
    force_field_utils.py
    legacy_job_scripts.py
  task_runner/                # High-throughput engine (scheduler/framework/etc.)
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
  common/                     # Shared config helpers
    config.py
  algorithms/                 # Core algorithms and generators
    calculate_params.py
    raspa3_generator.py
    raspa3_io.py
    auto_mser_raspa2.py
    auto_mser_raspa3.py
    cluster_info.py
```

## Mode Mapping (Menu -> Module)

1) Parameter Screening  
   - `raspa_calc.modes.parameter_screening` -> `scripts/shell/auto.sh` ->
     `raspa_calc.tools.parameter_screening`

2) High-Throughput Calculation  
   - `raspa_calc.modes.high_throughput` -> `raspa_calc.cli.task_runner`

3) Data Extraction  
   - `raspa_calc.modes.data_extractor` -> `raspa_calc.tools.data_extractor`
   - RASPA3 parser: `raspa_calc.tools.data_extractor_raspa3`

4) Warning Processing  
   - `raspa_calc.modes.warning_processor` -> `raspa_calc.tools.warning_processor`

5) Isotherm Plotting  
   - `raspa_calc.modes.isotherm_plotter` -> `raspa_calc.tools.isotherm_plotter`

6) CSV/CIF Filtering  
   - `raspa_calc.modes.ciffilter` -> `raspa_calc.tools.ciffilter`

## Python Entry Points

- `python -m raspa_calc` → main interactive menu
- `python -m raspa_calc.cli.task_runner` → high-throughput runner CLI
- `python -m raspa_calc.tools.data_extractor` → RASPA2/3 data extraction
- `python -m raspa_calc.tools.parameter_screening` → parameter screening
- `python -m raspa_calc.tools.isotherm_plotter` → isotherm plotting

## Shell Workflows and Templates

- `scripts/shell/auto.sh` and `scripts/shell/simulate_workflow.sh` are helper
  workflows invoked by the CLI modes.
- `scripts/shell/raspa_scale/` contains the `raspa-scale` implementation and
  shared libs (queue management, target detection, scheduler helpers).
- `job_templates/` is a stable top-level path for scheduler templates. Scripts
  resolve it via `RASPA_TOOL_DIR/job_templates` (and do not copy templates into
  the work directory).
