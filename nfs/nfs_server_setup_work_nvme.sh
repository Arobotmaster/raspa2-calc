#!/bin/bash
# 在 NFS 服务器上将 work 目录迁移到 NVMe 并单独导出

set -euo pipefail

usage() {
  cat <<'EOF'
用法: nfs_server_setup_work_nvme.sh [选项]

选项:
  --src-export   原共享根目录（默认 /shared/raspa2-calc）
  --work-export  work 新导出目录（默认 /srv/raspa2-calc-work）
  --rsync-only   只同步数据，不改 /etc/exports
  -h, --help     显示帮助
EOF
}

SRC_EXPORT="/shared/raspa2-calc"
WORK_EXPORT="/srv/raspa2-calc-work"
RSYNC_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src-export) SRC_EXPORT="${2:-}"; shift ;;
    --work-export) WORK_EXPORT="${2:-}"; shift ;;
    --rsync-only) RSYNC_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1"; usage; exit 2 ;;
  esac
  shift
done

if [ -z "$SRC_EXPORT" ] || [ -z "$WORK_EXPORT" ]; then
  echo "❌ 参数无效：SRC_EXPORT 或 WORK_EXPORT 为空"
  exit 1
fi

WORK_SRC="${SRC_EXPORT%/}/work"
WORK_DST="${WORK_EXPORT%/}"

echo "=== NFS work 迁移/导出 ==="
echo "源目录: $WORK_SRC"
echo "目标目录(NVMe): $WORK_DST"

if [ ! -d "$WORK_SRC" ]; then
  echo "❌ 源目录不存在: $WORK_SRC"
  exit 1
fi

sudo mkdir -p "$WORK_DST"

echo "开始同步数据（首次复制）..."
sudo rsync -aHAX --numeric-ids "$WORK_SRC"/ "$WORK_DST"/

if [ "$RSYNC_ONLY" -eq 1 ]; then
  echo "✅ 已完成 rsync，未修改 /etc/exports"
  exit 0
fi

echo "更新 /etc/exports..."
TMP_EXPORTS=$(mktemp)
python3 - "$SRC_EXPORT" "$WORK_EXPORT" "$TMP_EXPORTS" <<'PY'
import sys

src = sys.argv[1]
work = sys.argv[2]
tmp = sys.argv[3]

clients = []
lines = []
with open("/etc/exports", "r", encoding="utf-8") as fh:
    for raw in fh:
        line = raw.rstrip("\n")
        lines.append(raw)
        if line.strip().startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] == src:
            clients.append(" ".join(parts[1:]))

clients = list(dict.fromkeys(clients))
new_lines = lines[:]
if clients:
    for client in clients:
        new_lines.append(f"{work} {client}\n")
else:
    new_lines.append(f"{work} *(rw,sync,no_subtree_check,no_root_squash)\n")

with open(tmp, "w", encoding="utf-8") as fh:
    fh.writelines(new_lines)
PY

sudo cp -f "$TMP_EXPORTS" /etc/exports
rm -f "$TMP_EXPORTS" || true

sudo exportfs -rav

echo "✅ 已导出 work 目录: $WORK_DST"
echo "下一步：在所有客户端执行"
echo "  NFS_WORK_EXPORT=${WORK_DST} bash /home/zjp/raspa2-calc/.raspa_tools/nfs/nfs_client_setup.sh --recover"
