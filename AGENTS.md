# Repository Guidelines

## Project Structure & Module Organization
- `bin/`: shims (`raspa-calc`, `raspa-diagnose`, `raspa-status`, `raspa-scale`, `raspa-plot-isotherm`) forwarding to Python; keep names stable.
- `src/raspa_calc/`: core Python package (`entrypoints/`, `app/`, `domain/`, `infra/`, `runtime/`); CLI entry points live in `src/raspa_calc/entrypoints/`.
- `scripts/shell/`: shell tooling for submission/scale/workers.
- `scripts/shell/entrypoints/`: task submission/scale entry scripts; invoked by runners and `raspa-scale`.
- `scripts/shell/workers/`: worker scripts (`runjobs*.sh`) used by schedulers and local runs.
- `scripts/shell/templates/schedulers/`: SLURM/PBS/local submission templates; keep placeholder vars intact.
- `config.yaml` and `config/raspa3/`: runtime defaults and sample RASPA3 JSON; `raspa3json/` packaged templates; `raspa2-3/` converters; `figure/` docs assets.

## Build, Test, and Development Commands
- `pip install -r requirements.txt` — install Python deps.
- `./install.sh` — install CLI shims under `$HOME/raspa2-calc/.raspa_tools`.
- `RASPA_WORK_DIR=/path/to/work raspa-diagnose` — verify Python deps, scheduler tools, RASPA2/3 paths.
- `RASPA_WORK_DIR=/path/to/work raspa-calc` — main entry; respects `config.yaml`.
- `raspa-status -d output` / `raspa-scale status -d output` — check queues; `raspa-scale -i work/output` — tune concurrency; `raspa-plot-isotherm` — plot outputs.
- `python -m raspa_calc.entrypoints.parameter_screening --help` / `python -m raspa_calc.entrypoints.data_extractor --help` — quick CLI sanity after edits.

## Coding Style & Naming Conventions
- Python 3, 4-space indent; prefer small helpers over long procedures; use `os.path`/`pathlib` for paths.
- Keep user-facing prints concise and consistent with existing emoji/status prefixes; stick to bilingual-friendly tone already present.
- Config keys stay `snake_case` per `config.yaml`; avoid new hard-coded absolute paths—pull from config/env vars.
- Preserve stable CLI names/flags referenced by job templates; add a short usage block at file heads when adding modes.

## Testing Guidelines
- No automated suite; validate changes with `raspa-diagnose` plus a small local run in a disposable `work/` (e.g., `scripts/shell/templates/schedulers/local.sh` or `scripts/shell/simulate_workflow.sh`).
- When touching parsers (`data_extractor*`, `raspa_calc/domain/algorithms/raspa3_generator.py`), rerun against a tiny `output/` fixture and confirm expected rows/columns.
- For scheduler/template edits, dry-run with `bash -x scripts/shell/templates/schedulers/<script>.sh` and ensure required env vars and paths resolve.

## Commit & Pull Request Guidelines
- Use Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`); keep commits scoped by feature/mode (raspa2 vs raspa3).
- PRs: include summary, commands run (with paths), config assumptions, and any artifacts (logs/plots); link issues/tasks when relevant.

## Security & Configuration Tips
- Keep credentials and personal `work/` outputs out of the repo; prefer env vars for secrets.
- Review `config.yaml` paths before shared runs to avoid clobbering NFS state; set `RASPA_WORK_DIR` explicitly per job.
- Set `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` to `1` in job scripts to prevent oversubscription.
