# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RASPA 高通量计算工具 (RASPA High-Throughput Computing Tool) v2.4.0 - A molecular simulation platform for RASPA2/RASPA3 that supports parameter screening, high-throughput computing, data extraction, warning recovery, and isotherm plotting.

**Key Capabilities:**
- Dual RASPA2/RASPA3 version support with automatic detection
- High-throughput parallel execution (960+ CPU cores on SLURM clusters)
- Atomic file-based task queue system for NFS-safe concurrent access
- Five computational modes from parameter screening to data visualization

## Key Commands

### Installation
```bash
cd .raspa_tools && chmod +x install.sh && ./install.sh
source ~/.bashrc
raspa-diagnose  # Verify installation
```

### Main Entry Points
```bash
raspa-calc            # Main program (5 modes: parameter screening, high-throughput, data extraction, warning processing, isotherm plotting)
raspa-status          # Task status monitoring (-d for details, -r to reset failed, -m for real-time)
raspa-scale -i <dir>  # Interactive concurrency scaling
raspa-diagnose        # Environment diagnostics
```

### Dependencies
```bash
pip install numpy pandas gemmi openpyxl tqdm PyYAML
```

### Running Tests
```bash
# Test CIF parameter extraction
python .raspa_tools/scripts/python/calculate_params.py /path/to/structure.cif --cutoff 12.8

# Test data extraction (auto-detects RASPA version)
python .raspa_tools/scripts/python/data_extractor.py

# Test parameter screening
python .raspa_tools/scripts/python/parameter_screening.py
```

## Architecture

### Directory Structure
```
.raspa_tools/
├── bin/                    # CLI tools (raspa-calc, raspa-status, raspa-scale, raspa-diagnose)
├── scripts/python/         # Core Python modules
│   ├── raspa_calc.py       # Main entry point - mode selection and environment check
│   ├── task_runner.py      # High-throughput task orchestration (RASPA2/RASPA3)
│   ├── calculate_params.py # CIF parsing and UnitCells calculation using gemmi
│   ├── data_extractor.py   # RASPA2 output parsing and Excel/CSV export
│   ├── data_extractor_raspa3.py  # RASPA3 output parsing
│   ├── parameter_screening.py    # Parameter combination generation
│   ├── warning_processor.py      # Failed task recovery
│   └── isotherm_plotter.py       # Visualization
├── job_templates/          # Job submission scripts
│   ├── tasksrun.sh         # Main task submission (detects SLURM/PBS/local)
│   ├── runjobs.sh          # RASPA2 worker script with atomic task queue
│   ├── runjobs_raspa3.sh   # RASPA3 worker script
│   ├── sbatch.sh           # SLURM job template
│   └── pbs.sh              # PBS job template
└── config.yaml             # Main configuration file
```

### Configuration (config.yaml)

**Critical configuration sections:**
- `environment.raspa_version`: "raspa2" or "raspa3" (determines which version to use)
- `environment.work_dir`: Working directory for all tasks
- `environment.raspa_dir`: RASPA2 installation path (required for RASPA2)
- `environment.raspa3_conda_env`: RASPA3 conda environment name (default: "raspa3")
- `environment.raspa3_json_dir`: RASPA3 JSON files directory (must contain force_field.json and molecule .json files)
- `environment.raspa3_cif_base_path`: Base path for CIF files (RASPA3 uses full paths in JSON)
- `environment.raspa3_template_path`: Path to simulation.json template (RASPA3)
- `calculation.csv_file_path`: Input CSV with framework names
- `calculation.framework_column`: Column name containing framework identifiers (e.g., "refcode", "coreid")
- `calculation.default_molecules`: Gas molecules (space-separated, e.g., "CO2 CH4 N2")
- `calculation.use_custom_template`: Whether to use custom simulation.input (RASPA2 only)
- `calculation.template_path`: Path to custom simulation.input template (RASPA2)
- `parameter_screening.parameters`: Parameter combinations to test (generates Cartesian product)
- `parameter_screening.auto_unit_cells`: Auto-calculate unit cells from CIF using cutoff radius

**Configuration loading order** (first found wins):
1. `config.yaml` (current directory)
2. `.raspa_tools/config.yaml`
3. Relative to script location: `../../config.yaml`
4. `~/raspa2-calc/.raspa_tools/config.yaml`

### Task Queue System

High-throughput mode uses **atomic file-based task queues** with POSIX `noclobber` for NFS-safe concurrent access:

**Queue Files:**
- `.raspa_task_queue`: Shared task list (deprecated in favor of pointer-based system)
- `.raspa_queue/next_id`: Pointer to next task ID to process
- `.raspa_queue/last_id`: Pointer to last task ID in queue
- `.raspa_queue/retry.list`: Failed tasks for retry (atomic move operations)
- `.raspa_worker_limit`: Dynamic concurrency limit (modified by `raspa-scale`)
- `.workers/`: Worker registration directory (tracks active workers)

**Task State Machine (directory naming convention):**
1. `mc<N>`: Pending task (initial state)
2. `mc<N>__running`: Currently executing (renamed during execution)
3. `mc<N>__done`: Completed successfully (final state)
4. `mc<N>__failed`: Failed execution (moved to retry list)

**Concurrency Control Flow:**
1. Worker reads `.raspa_worker_limit` to check if it should continue
2. Worker atomically claims next task ID using file operations
3. Worker renames `mc<N>` → `mc<N>__running`
4. Worker executes RASPA simulation
5. Worker renames to `mc<N>__done` or `mc<N>__failed` based on result
6. `raspa-scale` can modify `.raspa_worker_limit` during execution
7. Workers exceeding limit exit gracefully after current task

**Why this design works on NFS:**
- Uses POSIX `set -o noclobber` with `>|` redirects for atomic writes
- File rename operations are atomic on NFS
- No shared state except atomic file operations
- Workers can run on different nodes safely

### RASPA Version Differences

| Aspect | RASPA2 | RASPA3 |
|--------|--------|--------|
| Input file | simulation.input (text) | simulation.json (JSON) |
| Extra files | None | force_field.json, molecule .json files |
| Execution | `$RASPA_DIR/bin/simulate` | `conda activate raspa3 && raspa3` |
| Output | Output/System_0/*.data | output/*.txt |
| Template params | Direct text replacement (sed) | JSON field updates (Python json module) |
| CIF location | Relative path in simulation.input | Full absolute path in simulation.json |
| Adsorption format | `Average loading absolute [mol/kg framework]` | `Abs. loading average [mol/kg-framework]` |

**Version Detection Logic:**
1. Check for `simulation.json` in mc directories → RASPA3
2. Check for `simulation.input` in mc directories → RASPA2
3. Fall back to `config.yaml` setting (`environment.raspa_version`)
4. Data extractor auto-detects version when processing output

### Key Python Functions & Architecture

**calculate_params.py** - CIF Processing & Unit Cell Calculation
- `get_cif_cell_parameters(cif_file, cutoff)`: Uses gemmi library to parse CIF files and calculate unit cells
- `process_structure_file(cif_file, cutoff)`: Main pipeline for CIF processing
- **Algorithm**: Perpendicular width method using vector cross products to ensure cutoff radius is satisfied in all directions
- **Key insight**: Must calculate perpendicular widths (not just cell lengths) because non-orthogonal cells require more repetitions

**task_runner.py** - High-Throughput Task Orchestration
- `get_slurm_cluster_resources()`: Queries SLURM via `sinfo -N` for per-node CPU availability
  - Considers hyperthreading (extracts sockets × cores from topology)
  - Accounts for node load to estimate actual free CPUs
  - Falls back to `sinfo -h -o %C` for cluster-wide summary
- `process_framework(framework, molecules, ...)`: Generates RASPA2 simulation.input files
  - Copies template and performs text substitution
  - Calculates UnitCells using calculate_params
- `process_framework_raspa3(framework, molecules, ...)`: Generates RASPA3 simulation.json files
  - Loads JSON template and updates fields
  - Copies force_field.json and molecule .json files to task directory
  - Uses absolute paths for CIF files
- **Job submission flow**: Python creates directories → Shell script detects scheduler → Submits SLURM/PBS/local jobs

**data_extractor.py** - RASPA2 Output Parsing
- `detect_raspa_version(base_path)`: Auto-detects RASPA version from file presence
- `RASPA_Output_Data`: Main parser class with precompiled regex patterns for performance
  - Extracts: absorption (multiple units), pressure, temperature, He void fraction
  - Extracts: framework density, Henry coefficient, adsorption heat, warnings
  - Supports: mol/kg, cm³/g, mg/g, cm³/cm³ units
  - **Performance optimization**: All regexes precompiled as class attributes
- `extract_data_from_directory(base_dir)`: Recursively processes all mc* directories

**data_extractor_raspa3.py** - RASPA3 Output Parsing
- Parses `output/*.txt` files with scientific notation support (e.g., `1.234567e+00`)
- Extracts from "Loadings" section specifically (avoids confusion with component definitions)
- Handles multiple components and pressure points
- Different regex patterns needed due to format differences vs RASPA2

**parameter_screening.py** - Parameter Combination Generation
- Generates Cartesian product of all parameter combinations from `config.yaml`
- Auto-calculates UnitCells if `auto_unit_cells: true` and cutoff parameters present
- Supports both RASPA2 text substitution and RASPA3 JSON modification
- Creates separate mc directories for each parameter combination

**Job Submission Scripts (job_templates/)**
- `tasksrun.sh`: Main entry point, detects SLURM/PBS/local and calls appropriate template
- `runjobs.sh` / `runjobs_raspa3.sh`: Worker scripts that claim tasks from queue
  - Read `.raspa_worker_limit` before claiming next task
  - Use atomic file operations for task claiming
  - Execute RASPA simulation in claimed directory
  - Mark task as done/failed based on output
- `sbatch.sh` / `pbs.sh`: SLURM/PBS job templates with proper environment setup

## Development Notes

### Environment Variables

**Required for RASPA2:**
```bash
export RASPA_DIR=/path/to/raspa2           # Must point to RASPA2 installation with bin/simulate
export RASPA_WORK_DIR=/path/to/work        # Working directory for calculations
```

**Required for RASPA3:**
```bash
export RASPA_WORK_DIR=/path/to/work        # Working directory
# RASPA3 uses conda environment, no RASPA_DIR needed
source ~/anaconda3/etc/profile.d/conda.sh
conda activate raspa3
```

**Performance & Threading Control:**
```bash
export OPENBLAS_NUM_THREADS=1              # Prevent BLAS thread conflicts
export OMP_NUM_THREADS=1                   # Limit OpenMP threads per task
export MKL_NUM_THREADS=1                   # Limit MKL threads per task
```
**Why limit threads?** High-throughput mode runs many parallel tasks. Each task should use 1 CPU core. Without these limits, BLAS/MKL will spawn multiple threads per task, causing severe oversubscription.

**Configuration Override (set by raspa_calc.py automatically):**
```bash
export RASPA_VERSION=raspa3                # Override config.yaml version
export RASPA_CIF_DIR=/path/to/cif          # Override CIF directory
export RASPA_CUTOFF_RADIUS=12.8            # Override cutoff radius
export RASPA_DEFAULT_MOLECULES="CO2 CH4"   # Override default molecules
export RASPA_CSV_FILE=/path/to/input.csv   # Override input CSV
export RASPA_FRAMEWORK_COLUMN=coreid       # Override framework column name
export RASPA3_JSON_DIR=/path/to/json       # RASPA3 JSON files directory
export RASPA3_CONDA_ENV=raspa3             # RASPA3 conda environment name
```

### Common Development Scenarios

**Adding a new gas molecule:**
1. For RASPA2: Add molecule definition to `$RASPA_DIR/share/raspa/molecules/`
2. For RASPA3: Create molecule JSON file in `raspa3_json_dir` (e.g., `H2.json`)
3. Update `calculation.default_molecules` in config.yaml
4. Test with parameter screening mode first before high-throughput

**Modifying simulation parameters:**
1. For RASPA2: Edit template at `calculation.template_path` (simulation.input)
2. For RASPA3: Edit template at `environment.raspa3_template_path` (simulation.json)
3. For parameter screening: Add to `parameter_screening.parameters` in config.yaml

**Debugging failed tasks:**
```bash
# Check task status
raspa-status -d output/

# Find failed tasks
find output/ -type d -name "mc*__failed"

# Check output logs
cat output/mc123__failed/Output/System_0/output_*.data    # RASPA2
cat output/mc123__failed/output/output_*.txt              # RASPA3

# Check SLURM logs (if using SLURM)
cat output/1log/slurm-*.out
```

**Manually resubmitting failed tasks:**
```bash
# Reset failed task status
for dir in output/mc*__failed; do
    mv "$dir" "${dir%__failed}"
done

# Or use raspa-status
raspa-status -r output/

# Then resubmit
raspa-calc  # Choose mode 2 (high-throughput)
```

**Testing individual components:**
```bash
# Test CIF parameter extraction with specific cutoff
python .raspa_tools/scripts/python/calculate_params.py /path/to/structure.cif --cutoff 12.8

# Test data extraction (auto-detects RASPA version)
cd work/output
python ../../.raspa_tools/scripts/python/data_extractor.py

# Test parameter screening without running simulations
python .raspa_tools/scripts/python/parameter_screening.py --dry-run

# Test SLURM resource detection
python -c "from task_runner import get_slurm_cluster_resources; import json; print(json.dumps(get_slurm_cluster_resources(), indent=2))"
```

**Monitoring cluster performance:**
```bash
# Real-time task status
raspa-status -m output/

# SLURM job status
squeue -u $USER
squeue -u $USER -t RUNNING | wc -l

# Check node utilization
sinfo -N -o "%N %C %O"  # Node CPU allocation and load

# Check worker limit
cat output/.raspa_worker_limit
```

### Multi-node Cluster Deployment

**Critical requirements:**
1. **NFS-mounted work directory**: All nodes must access the same filesystem
2. **Consistent conda environments**: RASPA3 conda env must exist on all nodes with same name
3. **Atomic operations**: System uses POSIX `noclobber` for atomic file locking across NFS
4. **Submit from NFS directory**: Always `cd /path/to/nfs/raspa2-calc` before running `raspa-calc`

**Verification steps:**
```bash
# On all nodes, verify NFS mount
df -h | grep raspa2-calc

# On all nodes, verify RASPA installation
which simulate  # RASPA2
conda activate raspa3 && which raspa3  # RASPA3

# Test atomic file operations (on one node)
cd /path/to/nfs/raspa2-calc
bash -c 'set -o noclobber; echo "test" > testfile' && echo "OK" || echo "FAILED"
```

**Scaling concurrency during execution:**
```bash
# Interactive mode (asks for confirmation)
raspa-scale -i work/output

# Auto mode (applies recommended concurrency)
raspa-scale -y work/output

# Manual mode (set specific limit)
raspa-scale 500 work/output
```

### Code Modification Guidelines

**When adding RASPA3 support to a component:**
1. Check `get_raspa_version_from_env()` or `detect_raspa_version()` for version
2. Load RASPA3 config with `load_raspa3_config()`
3. Use JSON operations instead of text replacement
4. Ensure force_field.json and molecule JSONs are copied to task directories
5. Use absolute CIF paths in simulation.json

**When modifying task queue logic:**
- Never use file locking mechanisms (not reliable on NFS)
- Use atomic rename operations (`mv` is atomic)
- Use `set -o noclobber` with `>|` for atomic writes
- Test with multiple concurrent workers on different nodes
- Check for race conditions by running 100+ parallel workers

**When adding new data extraction fields:**
1. Add regex pattern to `RASPA_Output_Data` class (RASPA2) or parsing function (RASPA3)
2. Update both Excel and CSV export logic
3. Test with multiple pressure points and components
4. Handle missing data gracefully (not all simulations output all fields)

### Performance Optimization Notes

**CIF Processing:**
- gemmi library is much faster than ase for CIF parsing
- Unit cell calculation is I/O bound (reading CIF files)
- Cache calculated parameters if processing same CIF multiple times

**Data Extraction:**
- Precompiled regex patterns (class attributes) are 10x faster than re.compile() per call
- Use multiprocessing for parallel extraction (ProcessPoolExecutor)
- Reading output files is I/O bound on NFS

**Task Queue:**
- Pointer-based queue (next_id/last_id) avoids scanning directories
- Atomic operations eliminate need for file locking
- 90% reduction in NFS I/O vs naive directory scanning

**SLURM Submission:**
- Job array mode (`sbatch --array=1-N%M`) is 50x faster than individual submits
- Batch submission reduces scheduler overhead
- Delay between submits prevents scheduler overload
