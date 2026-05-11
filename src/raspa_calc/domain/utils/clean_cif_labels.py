import argparse
import os
import re
import shutil
import sys

"""
CIF Label Cleaning Tool for RASPA3
----------------------------------
Usage:
1. Command Line: python clean_cif_labels.py "path/to/cif_folder" [--in-place] [--files file1.cif ...]
2. Interactive:  python clean_cif_labels.py (then follow prompt)

Description:
This script scans a directory for .cif files, identifies the _atom_site_label column,
and related atom-type columns, and removes numeric suffixes (e.g., 'Co1' -> 'Co').
Processed files are saved in a 'cleaned_cif' subfolder by default, or updated in place when --in-place is used.
Original files remain untouched unless --in-place is specified.
"""


def _clean_numbered_suffix(value):
    """Remove a trailing numeric suffix but preserve non-numeric names."""
    return re.sub(r'(?<=\D)\d+$', '', value)

def clean_cif_labels(directory, target_files=None, in_place=False):
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a valid directory.")
        return

    # Create output directory
    if in_place:
        output_dir = directory
    else:
        output_dir = os.path.join(directory, "cleaned_cif")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")

    cif_files = [f for f in os.listdir(directory) if f.lower().endswith('.cif')]
    target_set = set(os.path.basename(f) for f in target_files) if target_files else set()

    if not cif_files:
        print("No CIF files found in the directory.")
        return

    missing_targets = target_set - set(cif_files)
    if missing_targets:
        print(f"Warning: {len(missing_targets)} target files were not found and will be skipped: {', '.join(sorted(missing_targets))}")
        target_set = target_set & set(cif_files)

    if target_set:
        files_to_process = [f for f in cif_files if f in target_set]
        print(f"Found {len(cif_files)} CIF files. Cleaning {len(files_to_process)} targeted files{'' if in_place else ' (output under cleaned_cif)'}...")
    else:
        files_to_process = cif_files
        print(f"Found {len(files_to_process)} CIF files. Starting processing{'' if in_place else ' (output under cleaned_cif)'}...")

    if not files_to_process:
        print("No matching CIF files to process.")
        return

    for filename in files_to_process:
        filepath = os.path.join(directory, filename)
        output_path = os.path.join(output_dir, filename)
        process_file(filepath, output_path)

def process_file(filepath, output_path):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Failed to read {filepath}: {e}")
        return

    new_lines = []
    in_atom_loop = False
    headers = []
    target_indices = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for loop start
        if stripped.startswith('loop_'):
            loop_headers = []
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith('_'):
                loop_headers.append(lines[j].strip())
                j += 1
            
            target_headers = [
                '_atom_site_label',
                '_atom_site_type_symbol',
                '_atom_type_symbol',
            ]

            if any(h in loop_headers for h in target_headers):
                in_atom_loop = True
                headers = loop_headers
                target_indices = [headers.index(h) for h in target_headers if h in headers]
                # Keep headers
                new_lines.append(line)
                for _ in range(len(headers)):
                    new_lines.append(lines[i+1])
                    i += 1
                i += 1
                continue
            else:
                in_atom_loop = False
        
        if in_atom_loop:
            # End of loop detection
            if not stripped or stripped.startswith('_') or stripped.startswith('loop_') or stripped.startswith('data_'):
                in_atom_loop = False
                new_lines.append(line)
            else:
                # Process data row
                parts = stripped.split()
                if len(parts) >= len(headers):
                    new_parts = list(parts)
                    for idx in target_indices:
                        if idx < len(new_parts):
                            new_parts[idx] = _clean_numbered_suffix(new_parts[idx])
                    
                    # Reconstruct line with tab/space separation
                    new_line = "  ".join(new_parts) + "\n"
                    new_lines.append(new_line)
                else:
                    new_lines.append(line)
        else:
            new_lines.append(line)
        
        i += 1

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"Saved: {os.path.basename(output_path)}")
    except Exception as e:
        print(f"Failed to write {output_path}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean numbered CIF labels while preserving originals.")
    parser.add_argument("directory", nargs="?", help="Directory containing CIF files")
    parser.add_argument("--files", nargs="+", help="Specific CIF filenames to clean (others will be copied as-is)")
    parser.add_argument("--in-place", action="store_true", help="Modify target CIF files in place instead of writing to cleaned_cif")

    args = parser.parse_args()

    print("=== CIF Label Cleaner ===")
    if args.directory:
        target_dir = args.directory
    else:
        print("Usage: python clean_cif_labels.py \"path/to/cif_folder\" --files file1.cif file2.cif")
        target_dir = input("Or enter the directory path now: ").strip()
    
    if target_dir:
        clean_cif_labels(target_dir, target_files=args.files, in_place=args.in_place)
        if args.in_place:
            print("\nProcessing complete. Files updated in place.")
        else:
            print("\nProcessing complete. Check the 'cleaned_cif' folder.")
    else:
        print("No directory provided. Exiting.")
