#!/usr/bin/env python3
"""Utilities for trimming RASPA3 force_field.json files to only the atoms in a system."""

import json
import logging
import os
import re
import shutil
from typing import Iterable, Optional, Set

try:
    import gemmi
except ImportError:
    gemmi = None

logger = logging.getLogger("force_field_utils")


def _normalize_symbol(symbol: str) -> str:
    """Normalize atomic symbols (e.g., co -> Co)."""
    if not symbol:
        return ""
    cleaned = symbol.strip()
    if not cleaned:
        return ""
    if cleaned[0].isalpha():
        if len(cleaned) == 1:
            cleaned = cleaned.upper()
        else:
            cleaned = cleaned[0].upper() + cleaned[1:]
    if len(cleaned) == 1:
        return cleaned
    match = re.match(r"^([A-Z][a-z]?)(\d+)$", cleaned)
    if match:
        return match.group(1)
    return cleaned


def _extract_atoms_from_cif(cif_path: str, log: logging.Logger) -> Set[str]:
    """Read a CIF and return the unique `_atom_site_type_symbol` values."""
    atoms: Set[str] = set()
    if not cif_path or not os.path.exists(cif_path):
        return atoms

    if gemmi is None:
        log.warning("gemmi 未安装，无法解析 CIF: %s", cif_path)
        return atoms

    try:
        block = gemmi.cif.read_file(cif_path).sole_block()
        for tag in ("_atom_site_type_symbol", "_atom_type_symbol"):
            values = block.find_values(tag)
            for value in values:
                symbol = _normalize_symbol(value)
                if symbol:
                    atoms.add(symbol)
            if atoms:
                break
    except Exception as exc:  # noqa: BLE001
        log.warning("解析 CIF 时出错 %s: %s", cif_path, exc)

    return atoms


def _extract_atoms_from_components(
    json_dir: str, component_names: Iterable[str], log: logging.Logger
) -> Set[str]:
    """Collect pseudo-atom names from molecule definition JSON files."""
    atoms: Set[str] = set()
    if not json_dir or not component_names:
        return atoms

    for name in component_names:
        if not name:
            continue

        mol_path = os.path.join(json_dir, f"{name}.json")
        if not os.path.exists(mol_path):
            log.warning("分子定义文件不存在: %s", mol_path)
            continue

        try:
            with open(mol_path, "r", encoding="utf-8") as f:
                mol_data = json.load(f)
        except Exception as exc:  # noqa: BLE001
            log.warning("读取分子定义文件失败 %s: %s", mol_path, exc)
            continue

        pseudo_atoms = mol_data.get("pseudoAtoms") or mol_data.get("PseudoAtoms") or []
        for entry in pseudo_atoms:
            atom_name = None
            if isinstance(entry, (list, tuple)) and entry:
                atom_name = entry[0]
            elif isinstance(entry, dict):
                atom_name = entry.get("name") or entry.get("Name")

            if atom_name:
                atoms.add(str(atom_name))

    return atoms


def write_filtered_force_field(
    force_field_src: str,
    destination: str,
    cif_path: Optional[str] = None,
    json_dir: Optional[str] = None,
    component_names: Optional[Iterable[str]] = None,
    log: Optional[logging.Logger] = None,
) -> bool:
    """
    Write a filtered force_field.json that only contains atoms used by the framework and components.

    If CIF parsing fails or no atoms can be determined, the function falls back to copying the
    original force_field.json unchanged.

    Returns:
        bool: True if the destination file was written (filtered or copied), False otherwise.
    """
    log = log or logger

    if not os.path.exists(force_field_src):
        log.warning("force_field.json 不存在: %s", force_field_src)
        return False

    framework_atoms = _extract_atoms_from_cif(cif_path, log) if cif_path else set()
    if cif_path and not framework_atoms:
        log.warning("未能从 CIF 解析出原子类型，回退复制完整力场文件: %s", cif_path)
        shutil.copy2(force_field_src, destination)
        return True

    component_atoms = _extract_atoms_from_components(json_dir, component_names or [], log)
    required_atoms = framework_atoms | component_atoms

    # If we cannot determine any atoms, copy the original to avoid breaking runs.
    if not required_atoms:
        log.debug("未找到需要筛选的原子类型，复制完整 force_field.json")
        shutil.copy2(force_field_src, destination)
        return True

    try:
        with open(force_field_src, "r", encoding="utf-8") as f:
            force_field_data = json.load(f)
    except Exception as exc:  # noqa: BLE001
        log.warning("读取 force_field.json 失败，回退复制完整文件: %s", exc)
        shutil.copy2(force_field_src, destination)
        return False

    pseudo_atoms = [
        entry
        for entry in force_field_data.get("PseudoAtoms", [])
        if isinstance(entry, dict) and entry.get("name") in required_atoms
    ]
    self_interactions = [
        entry
        for entry in force_field_data.get("SelfInteractions", [])
        if isinstance(entry, dict) and entry.get("name") in required_atoms
    ]

    missing = required_atoms - {
        entry.get("name") for entry in force_field_data.get("PseudoAtoms", []) if isinstance(entry, dict)
    }
    if missing:
        log.warning("力场中缺少以下原子定义: %s", ", ".join(sorted(missing)))

    # Preserve key order by mutating a shallow copy instead of rebuilding.
    filtered_force_field = dict(force_field_data)
    filtered_force_field["PseudoAtoms"] = pseudo_atoms
    filtered_force_field["SelfInteractions"] = self_interactions

    if not pseudo_atoms or not self_interactions:
        log.warning("筛选后力场为空，回退复制完整 force_field.json")
        shutil.copy2(force_field_src, destination)
        return False

    with open(destination, "w", encoding="utf-8") as f:
        json.dump(filtered_force_field, f, indent=2)

    log.debug(
        "已生成筛选后的 force_field.json，包含 %d 个原子定义 (框架 %d, 组分 %d)",
        len(pseudo_atoms),
        len(framework_atoms),
        len(component_atoms),
    )
    return True
