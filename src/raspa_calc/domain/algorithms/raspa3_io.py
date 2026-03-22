import json
import logging
import os
import shutil

from raspa_calc.domain.utils.force_field_utils import write_filtered_force_field

logger = logging.getLogger(__name__)


def ensure_system_config(sim_config):
    if not sim_config.get("Systems"):
        sim_config["Systems"] = [{}]
    return sim_config["Systems"][0]


def apply_system_settings(sim_config, cif_path=None, unit_cells=None, void_fraction=None, use_abs_cif=False):
    system_cfg = ensure_system_config(sim_config)
    if cif_path and os.path.exists(cif_path):
        system_cfg["Name"] = os.path.abspath(cif_path) if use_abs_cif else cif_path
    if unit_cells is not None:
        system_cfg["NumberOfUnitCells"] = list(unit_cells)
    if void_fraction is not None:
        system_cfg["HeliumVoidFraction"] = void_fraction
    return system_cfg


def apply_component_names(sim_config, component_names, log=None):
    if not component_names or "Components" not in sim_config:
        return

    components = sim_config.get("Components") or []
    for i, component in enumerate(components):
        if not isinstance(component, dict):
            continue
        chosen = component_names[min(i, len(component_names) - 1)]
        component["Name"] = chosen
        if log:
            log.info(f"设置 Components[{i}].Name: {chosen}")


def apply_mser_settings(sim_config, mser_enable=False, add_cycles=None, print_every=None):
    if not mser_enable:
        return
    cycles = add_cycles or sim_config.get("NumberOfCycles", 1000)
    sim_config["NumberOfCycles"] = cycles
    sim_config["NumberOfInitializationCycles"] = 0
    sim_config["NumberOfEquilibrationCycles"] = 0
    if print_every is not None:
        sim_config["PrintEvery"] = print_every


def finalize_simulation_config(sim_config):
    sim_config.pop("WriteBinaryRestartEvery", None)
    sim_config.pop("RestartFromBinaryFile", None)


def write_simulation_json(sim_config, output_path, ensure_ascii=True):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sim_config, f, indent=2, ensure_ascii=ensure_ascii)


def copy_force_field_and_components(json_dir, output_dir, component_names=None, cif_path=None, log=None):
    if not json_dir or not os.path.isdir(json_dir):
        return False

    log = log or logger
    os.makedirs(output_dir, exist_ok=True)

    force_field_src = os.path.join(json_dir, "force_field.json")
    if os.path.exists(force_field_src):
        dest = os.path.join(output_dir, "force_field.json")
        write_filtered_force_field(
            force_field_src,
            dest,
            cif_path=cif_path,
            json_dir=json_dir,
            component_names=component_names,
            log=log,
        )
        log.debug(f"复制 force_field.json 到 {dest}（已按 CIF/组分筛选）")
    else:
        log.warning(f"force_field.json 不存在: {force_field_src}")

    for name in component_names or []:
        if not name:
            continue
        mol_src = os.path.join(json_dir, f"{name}.json")
        if os.path.exists(mol_src):
            shutil.copy2(mol_src, os.path.join(output_dir, f"{name}.json"))
            log.debug(f"复制 {name}.json 到 {output_dir}")
        else:
            log.warning(f"分子定义文件不存在: {mol_src}")

    return True
