import os

from .logging_utils import logger


def locate_cif_file(framework_name, cif_dir):
    """Locate CIF file for a given framework name within a directory."""
    clean_name = framework_name
    if isinstance(clean_name, str) and clean_name.lower().endswith(".cif"):
        clean_name = clean_name[:-4]

    candidates = [
        os.path.join(cif_dir, f"{clean_name}.cif"),
        os.path.join(cif_dir, f"{clean_name}"),
        os.path.join(cif_dir, f"{str(clean_name).upper()}.cif"),
        os.path.join(cif_dir, f"{str(clean_name).lower()}.cif"),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def count_numbered_labels(cif_path):
    """Count labels that contain numeric suffixes in a CIF file."""
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

            if any(tag.startswith("_atom_site_label") for tag in tags):
                try:
                    label_idx = tags.index("_atom_site_label")
                except ValueError:
                    label_idx = -1

                if label_idx >= 0:
                    k = i
                    while k < len(lines):
                        row = lines[k].strip()
                        if not row or row.startswith("#"):
                            k += 1
                            continue
                        if row.startswith("loop_") or row.startswith("_"):
                            break

                        parts = row.split()
                        if len(parts) > label_idx:
                            label = parts[label_idx].strip().strip("'\"")
                            if any(ch.isdigit() for ch in label):
                                count += 1
                        k += 1
                    i = k
                    continue
        i += 1

    return count
