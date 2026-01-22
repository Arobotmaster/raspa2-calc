import copy
import json
import logging
import math
import os
import subprocess

from raspa_calc.algorithms.calculate_params import process_structure_file
from raspa_calc.algorithms.raspa3_io import (
    apply_component_names,
    apply_mser_settings,
    apply_system_settings,
    copy_force_field_and_components,
    finalize_simulation_config,
    write_simulation_json,
)

from .cif import locate_cif_file
from .logging_utils import logger


def check_structure_files(framework_name, custom_cif_dir=None):
    """Check CIF structure file exists."""
    clean_name = framework_name
    if clean_name.lower().endswith(".cif"):
        clean_name = clean_name[:-4]

    if custom_cif_dir:
        cif_dir = custom_cif_dir
    else:
        cif_dir = os.environ.get("RASPA_CIF_DIR")
        if not cif_dir:
            current_dir = os.getcwd()
            cif_dir = os.path.join(current_dir, "data", "cif")

    cif_file = locate_cif_file(clean_name, cif_dir)
    if cif_file:
        default_path = os.path.join(cif_dir, f"{clean_name}.cif")
        if os.path.abspath(cif_file) != os.path.abspath(default_path):
            logger.info(f"找到框架 {framework_name} 的替代CIF文件: {cif_file}")
        return cif_file

    from raspa_calc.algorithms.calculate_params import check_structure_files as check_cif_files
    cif_file = check_cif_files(clean_name, cif_dir)
    if cif_file:
        return cif_file

    if os.path.exists(cif_dir):
        logger.debug(f"CIF目录 {cif_dir} 中的文件:")
        for file in os.listdir(cif_dir):
            logger.debug(f"  - {file}")

    logger.error(f"找不到框架 {framework_name} 的CIF结构文件")
    return None


def process_framework(
    topdir,
    subdir,
    counter,
    framework_name,
    cutoff,
    void_csv_file=None,
    void_fraction_column=None,
    template_path=None,
    molecule_name="I2",
    cif_dir=None,
    framework_column=None,
    result_cache=None,
):
    """Process single framework (RASPA2)."""
    md_dir = os.path.join(topdir, subdir, f"mc{counter}")
    os.makedirs(md_dir, exist_ok=True)

    task_log_file = os.path.join(md_dir, "raspa_calculation.log")
    task_handler = logging.FileHandler(task_log_file, mode="w")
    task_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    task_handler.setLevel(logging.INFO)

    current_logger = logging.getLogger()
    current_logger.addHandler(task_handler)

    try:
        try:
            structure_file = check_structure_files(framework_name, cif_dir)
            if structure_file is None:
                logger.error(f"找不到框架 {framework_name} 的结构文件")
                return False

            success, unit_cells, void_fraction = process_structure_file(
                structure_file,
                cutoff,
                csv_file=void_csv_file,
                void_fraction_column=void_fraction_column,
                framework_column=framework_column,
                result_cache=result_cache,
            )
            if not success:
                return False

            if template_path and os.path.isfile(template_path):
                sim_input_file = template_path
                logger.info(f"使用自定义模板: {template_path}")
            else:
                logger.error("缺少 RASPA2 模板，请在 config.yaml 中设置 template_path 指向可用的 simulation.input")
                return False

            try:
                subprocess.run(f"cp -rf {sim_input_file} {md_dir}/", shell=True, check=True, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError:
                return False

            sim_input_path = os.path.join(md_dir, "simulation.input")
            if not os.path.exists(sim_input_path):
                return False

            with open(sim_input_path, "r") as f:
                lines = f.readlines()

            updated_lines = []
            molecule_list = molecule_name.split() if isinstance(molecule_name, str) else [molecule_name]
            mser_enable = os.environ.get("RASPA_MSER_ENABLE", "false").lower() == "true"
            mser_add_cycles = int(os.environ.get("RASPA_MSER_ADD_CYCLES", "500")) if mser_enable else None
            seen_number_cycles = seen_init_cycles = seen_equil_cycles = False
            seen_continue = seen_restart = seen_print = False

            for line in lines:
                if line.startswith("FrameworkName"):
                    updated_lines.append(f"FrameworkName {framework_name}\n")
                elif line.startswith("UnitCells"):
                    updated_lines.append(f"UnitCells {unit_cells[0]} {unit_cells[1]} {unit_cells[2]}\n")
                elif line.startswith("HeliumVoidFraction"):
                    updated_lines.append(f"HeliumVoidFraction {void_fraction}\n")
                elif mser_enable and line.lower().startswith("numberofcycles"):
                    seen_number_cycles = True
                    updated_lines.append(f"NumberOfCycles {mser_add_cycles}\n")
                elif mser_enable and line.lower().startswith("numberofinitializationcycles"):
                    seen_init_cycles = True
                    updated_lines.append("NumberOfInitializationCycles 0\n")
                elif mser_enable and line.lower().startswith("numberofequilibrationcycles"):
                    seen_equil_cycles = True
                    updated_lines.append("NumberOfEquilibrationCycles 0\n")
                elif mser_enable and line.lower().startswith("restartfile"):
                    seen_restart = True
                    updated_lines.append("RestartFile no\n")
                elif mser_enable and line.lower().startswith("printevery"):
                    seen_print = True
                    updated_lines.append("PrintEvery 1\n")
                elif line.startswith("Component ") and "MoleculeName" in line:
                    parts = line.split()
                    if len(parts) >= 3 and parts[0] == "Component" and parts[2] == "MoleculeName":
                        try:
                            component_idx = int(parts[1])
                            if component_idx < len(molecule_list):
                                molecule = molecule_list[component_idx]
                                prefix = line[: line.find("MoleculeName") + len("MoleculeName")]
                                updated_lines.append(f"{prefix}   {molecule}\n")
                            else:
                                molecule = molecule_list[0]
                                prefix = line[: line.find("MoleculeName") + len("MoleculeName")]
                                updated_lines.append(f"{prefix}   {molecule}\n")
                        except (ValueError, IndexError):
                            updated_lines.append(line)
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)

            if mser_enable:
                if not seen_number_cycles:
                    updated_lines.append(f"NumberOfCycles {mser_add_cycles}\n")
                if not seen_init_cycles:
                    updated_lines.append("NumberOfInitializationCycles 0\n")
                if not seen_equil_cycles:
                    updated_lines.append("NumberOfEquilibrationCycles 0\n")
                if not seen_restart:
                    updated_lines.append("RestartFile no\n")
                if not seen_print:
                    updated_lines.append("PrintEvery 1\n")

            with open(sim_input_path, "w") as f:
                f.writelines(updated_lines)

            return True

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.debug(f"Error processing structure {framework_name}: {e}")
            return False
    finally:
        current_logger.removeHandler(task_handler)
        task_handler.close()


def process_framework_raspa3(
    topdir,
    subdir,
    counter,
    framework_name,
    cutoff,
    void_csv_file=None,
    void_fraction_column=None,
    template_path=None,
    molecule_name="CO2",
    cif_base_path=None,
    json_dir=None,
    framework_column=None,
    result_cache=None,
):
    """Process single framework (RASPA3)."""
    md_dir = os.path.join(topdir, subdir, f"mc{counter}")
    os.makedirs(md_dir, exist_ok=True)

    task_log_file = os.path.join(md_dir, "raspa_calculation.log")
    task_handler = logging.FileHandler(task_log_file, mode="w")
    task_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    task_handler.setLevel(logging.INFO)

    current_logger = logging.getLogger()
    current_logger.addHandler(task_handler)

    try:
        try:
            cif_path = None
            if cif_base_path:
                cif_path = locate_cif_file(framework_name, cif_base_path)

            if cif_path is None:
                logger.error(f"找不到框架 {framework_name} 的 CIF 文件")
                return False

            success, unit_cells, void_fraction = process_structure_file(
                cif_path,
                cutoff,
                csv_file=void_csv_file,
                void_fraction_column=void_fraction_column,
                framework_column=framework_column,
                result_cache=result_cache,
            )
            if not success:
                try:
                    cell_params = {}
                    with open(cif_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("_cell_length_a"):
                                cell_params["a"] = float(line.split()[1].split("(")[0])
                            elif line.startswith("_cell_length_b"):
                                cell_params["b"] = float(line.split()[1].split("(")[0])
                            elif line.startswith("_cell_length_c"):
                                cell_params["c"] = float(line.split()[1].split("(")[0])

                    if "a" in cell_params and "b" in cell_params and "c" in cell_params:
                        unit_a = max(1, math.ceil(2 * cutoff / cell_params["a"]))
                        unit_b = max(1, math.ceil(2 * cutoff / cell_params["b"]))
                        unit_c = max(1, math.ceil(2 * cutoff / cell_params["c"]))
                        unit_cells = [unit_a, unit_b, unit_c]
                        void_fraction = 0.5
                    else:
                        unit_cells = [1, 1, 1]
                        void_fraction = 0.5
                except Exception:
                    unit_cells = [1, 1, 1]
                    void_fraction = 0.5

            if template_path and os.path.isfile(template_path):
                sim_template_file = template_path
            else:
                tool_dir = os.environ.get("HOME", "") + "/raspa2-calc/.raspa_tools"
                sim_template_file = os.path.join(tool_dir, "raspa3json", "CO2", "simulation.json")
                if not os.path.isfile(sim_template_file):
                    logger.error("找不到 RASPA3 模板文件，请在 config.yaml 设置 raspa3_template_path 指向可用的 simulation.json")
                    return False

            with open(sim_template_file, "r", encoding="utf-8") as f:
                sim_config = json.load(f)

            sim_config = copy.deepcopy(sim_config)

            apply_system_settings(
                sim_config,
                cif_path=cif_path,
                unit_cells=unit_cells,
                void_fraction=void_fraction,
                use_abs_cif=False,
            )

            molecule_list = molecule_name.split() if isinstance(molecule_name, str) else [molecule_name]
            apply_component_names(sim_config, molecule_list)

            mser_enable = os.environ.get("RASPA_MSER_ENABLE", "false").lower() == "true"
            if mser_enable:
                try:
                    mser_add_cycles = int(os.environ.get("RASPA_MSER_ADD_CYCLES", "500"))
                except ValueError:
                    mser_add_cycles = 500
                apply_mser_settings(sim_config, mser_enable=mser_enable, add_cycles=mser_add_cycles)

            finalize_simulation_config(sim_config)

            sim_path = os.path.join(md_dir, "simulation.json")
            write_simulation_json(sim_config, sim_path)

            if json_dir and os.path.isdir(json_dir):
                copy_force_field_and_components(
                    json_dir,
                    md_dir,
                    component_names=molecule_list,
                    cif_path=cif_path,
                    log=logger,
                )

            return True

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.debug(f"RASPA3 处理框架 {framework_name} 时出错: {e}")
            return False
    finally:
        current_logger.removeHandler(task_handler)
        task_handler.close()


def _process_framework_wrapper(args):
    """Wrapper for parallel processing of frameworks."""
    func_name, kwargs = args
    result_cache = kwargs.get("result_cache")

    initial_keys = set(result_cache.keys()) if result_cache else set()

    success = False
    try:
        if func_name == "raspa3":
            success = process_framework_raspa3(**kwargs)
        else:
            success = process_framework(**kwargs)
    except Exception as e:
        logger.error(f"Error in worker for {kwargs.get('framework_name')}: {e}")
        return False, {}

    new_entries = {}
    if result_cache:
        current_keys = set(result_cache.keys())
        new_keys = current_keys - initial_keys
        for k in new_keys:
            new_entries[k] = result_cache[k]

    return success, new_entries
