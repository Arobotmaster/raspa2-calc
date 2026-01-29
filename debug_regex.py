
import re
import os

filename = "output_ZIF-8_pacman_2.2.2_298.000000_1e+06.data"

_FRAMEWORK_NAME_PATTERNS = (
    re.compile(r'output_(.+?)_\d+\.\d+_\d+\.\d+_\d+\.data'),
    re.compile(r'output_(.+?)_\d+(?:\.\d+)+(?:_\d+(?:\.\d+)*)*(?:\.data)?$'),
    re.compile(r'output_(.+?)_\d+_\d+(?:\.data)?$'),
    re.compile(r'output_([^._]+)'),
)

print(f"Testing filename: {filename}")
for i, pattern in enumerate(_FRAMEWORK_NAME_PATTERNS):
    match = pattern.search(filename)
    if match:
        print(f"Pattern {i+1} matched: {match.group(1)}")
    else:
        print(f"Pattern {i+1} failed")

try:
    import yaml
    print("PyYAML is installed.")
except ImportError:
    print("PyYAML is NOT installed.")
