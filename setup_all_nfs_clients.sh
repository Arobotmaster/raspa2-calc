#!/bin/bash
# Compatibility wrapper (moved to .raspa_tools/nfs/)

set -euo pipefail

exec "$(dirname "$0")/nfs/nfs_setup_all_nodes.sh" "$@"
