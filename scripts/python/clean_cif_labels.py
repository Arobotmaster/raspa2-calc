import os
import re
import sys

"""
CIF Label Cleaning Tool for RASPA3
----------------------------------
Usage:
1. Command Line: python clean_cif_labels.py "path/to/cif_folder"
2. Interactive:  python clean_cif_labels.py (then follow prompt)

Description:
This script scans a directory for .cif files, identifies the _atom_site_label column,
and removes all numeric suffixes (e.g., 'Co1' -> 'Co').
Processed files are saved in a 'cleaned_cif' subfolder relative to the input path.
Original files remain untouched.
"""

def clean_cif_labels(directory):
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a valid directory.")
        return

    # Create output directory
    output_dir = os.path.join(directory, "cleaned_cif")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")

    cif_files = [f for f in os.listdir(directory) if f.lower().endswith('.cif')]
    
    if not cif_files:
        print("No CIF files found in the directory.")
        return

    print(f"Found {len(cif_files)} CIF files. Starting processing...")

    for filename in cif_files:
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
    label_idx = -1

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
            
            if '_atom_site_label' in loop_headers:
                in_atom_loop = True
                headers = loop_headers
                label_idx = headers.index('_atom_site_label')
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
                    original_label = parts[label_idx]
                    # Remove all numbers from the label
                    cleaned_label = re.sub(r'\d+', '', original_label)
                    
                    new_parts = list(parts)
                    new_parts[label_idx] = cleaned_label
                    
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
    print("=== CIF Label Cleaner ===")
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        print("Usage: python clean_cif_labels.py \"path/to/cif_folder\"")
        target_dir = input("Or enter the directory path now: ").strip()
    
    if target_dir:
        clean_cif_labels(target_dir)
        print("\nProcessing complete. Check the 'cleaned_cif' folder.")
    else:
        print("No directory provided. Exiting.")
