import os

from .logging_utils import logger


def locate_cif_file(framework_name, cif_dir):
    """Locate CIF file for a given framework name within a directory."""
    if not cif_dir or not os.path.isdir(cif_dir):
        return None

    clean_name = framework_name
    if isinstance(clean_name, str) and clean_name.lower().endswith(".cif"):
        clean_name = clean_name[:-4]

    direct_match = os.path.join(cif_dir, f"{clean_name}.cif")
    if os.path.exists(direct_match):
        return direct_match

    candidates = [
        f"{clean_name}.cif",
        f"{clean_name}.CIF",
        f"{str(clean_name).upper()}.cif",
        f"{str(clean_name).lower()}.cif",
    ]

    for filename in os.listdir(cif_dir):
        if os.path.splitext(filename)[1].lower() != ".cif":
            continue
        base_name = os.path.splitext(filename)[0]
        if base_name.lower() == str(clean_name).lower() or filename in candidates:
            return os.path.join(cif_dir, filename)

    base_name = os.path.basename(str(clean_name))
    if base_name and base_name != clean_name:
        candidates_base = [
            f"{base_name}.cif",
            f"{base_name}.CIF",
            f"{base_name.upper()}.cif",
            f"{base_name.lower()}.cif",
        ]
        for filename in os.listdir(cif_dir):
            if os.path.splitext(filename)[1].lower() != ".cif":
                continue
            stem = os.path.splitext(filename)[0]
            if stem.lower() == base_name.lower() or filename in candidates_base:
                return os.path.join(cif_dir, filename)
    return None


def count_numbered_labels(cif_path):
    """Count numbered atom-site tokens in a CIF file.

    Historically this check only scanned `_atom_site_label`, but some CIF files
    store numbered values in `_atom_site_type_symbol` (e.g. `Mg0`, `C10`,
    `Zr12`). Those values later get treated as framework atom types during the
    RASPA3 force-field filtering step, so they must be detected here as well.
    """
    try:
        with open(cif_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as exc:
        logger.warning(f"读取 CIF 失败，跳过标签检查: {cif_path} ({exc})")
        return 0

    count = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.lower().startswith("loop_"):
            tags = []
            i += 1
            while i < len(lines):
                l = lines[i].strip()
                if l.startswith("_"):
                    tags.append(l)
                    i += 1
                else:
                    break

            target_indices = []
            for target_tag in (
                "_atom_site_label",
                "_atom_site_type_symbol",
                "_atom_type_symbol",
            ):
                try:
                    target_indices.append(tags.index(target_tag))
                except ValueError:
                    continue

            if target_indices:
                k = i
                while k < len(lines):
                    row = lines[k].strip()
                    if not row or row.startswith("#"):
                        k += 1
                        continue
                    if row.startswith("loop_") or row.startswith("_"):
                        break

                    parts = row.split()
                    for idx in target_indices:
                        if len(parts) <= idx:
                            continue
                        value = parts[idx].strip().strip("'\"")
                        if any(ch.isdigit() for ch in value):
                            count += 1
                    k += 1
                i = k
                continue
            continue
        i += 1

    return count
