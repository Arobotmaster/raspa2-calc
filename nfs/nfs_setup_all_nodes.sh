#!/bin/bash
# 批量配置所有节点的 NFS 客户端（含 Stale file handle 修复）

set -euo pipefail

NODES=("10.10.14.6" "10.10.14.7" "10.10.14.11")
NODE_NAMES=("master-node" "worker-node-01" "worker-node-02")
NFS_SERVER="${NFS_SERVER:-10.10.14.12}"
NFS_EXPORT="${NFS_EXPORT:-/shared/raspa2-calc}"
CLIENT_MOUNTPOINT="${CLIENT_MOUNTPOINT:-/home/zjp/raspa2-calc}"
SCRIPT_SRC="${SCRIPT_SRC:-${NFS_EXPORT}/.raspa_tools/nfs/nfs_client_setup.sh}"
REMOTE_SCRIPT="${REMOTE_SCRIPT:-nfs_client_setup.sh}"
SSH_USER="${SSH_USER:-zjp}"
AUTO_RUN=0
MODE="${1:-setup}" # setup | recover

usage() {
  cat <<EOF
用法: nfs_setup_all_nodes.sh [setup|recover] [--run]

说明:
  setup   : 分发 nfs_client_setup.sh（默认），并提示在各节点执行
  recover : 对所有节点执行 --recover（修复 Stale file handle）

选项:
  --run   : 复制后自动在远端执行（需要 ${SSH_USER} 具备 sudo 权限）

环境变量（可选）:
  SSH_USER           默认 zjp
  NFS_SERVER         默认 10.10.14.12
  NFS_EXPORT         默认 /shared/raspa2-calc
  CLIENT_MOUNTPOINT  默认 /home/zjp/raspa2-calc
  SCRIPT_SRC         默认 \${NFS_EXPORT}/.raspa_tools/nfs/nfs_client_setup.sh
EOF
}

shift_args=0
for arg in "$@"; do
  case "$arg" in
    --run) AUTO_RUN=1; shift_args=$((shift_args+1)) ;;
    -h|--help) usage; exit 0 ;;
  esac
done

if [[ "$MODE" != "setup" && "$MODE" != "recover" ]]; then
  echo "未知模式: $MODE"
  usage
  exit 2
fi

echo "=== 批量处理 NFS 客户端（mode=${MODE}, user=${SSH_USER}） ==="
echo "时间: $(date)"
echo ""

if [[ ! -f "$SCRIPT_SRC" ]]; then
  echo "❌ 找不到客户端脚本: $SCRIPT_SRC"
  echo "   请确认服务器本地路径 $NFS_EXPORT 存在，并包含 .raspa_tools/nfs/nfs_client_setup.sh"
  exit 1
fi

for i in "${!NODES[@]}"; do
  NODE_IP="${NODES[i]}"
  NODE_NAME="${NODE_NAMES[i]}"

  echo "【${NODE_NAME} (${NODE_IP})】"

  if ! ping -c 1 "$NODE_IP" >/dev/null 2>&1; then
    echo "❌ 节点不可达，跳过"
    echo ""
    continue
  fi

  echo "复制脚本到远端..."
  if scp -q "$SCRIPT_SRC" "${SSH_USER}@${NODE_IP}:~/${REMOTE_SCRIPT}"; then
    echo "✅ 复制成功"
  else
    echo "❌ 复制失败（检查 SSH 权限/网络）"
    echo ""
    continue
  fi

  if [[ "$AUTO_RUN" = "1" ]]; then
    echo "远端执行..."
    if [[ "$MODE" = "recover" ]]; then
      ssh -o StrictHostKeyChecking=no "${SSH_USER}@${NODE_IP}" "bash ~/${REMOTE_SCRIPT} --recover" || true
    else
      ssh -o StrictHostKeyChecking=no "${SSH_USER}@${NODE_IP}" "bash ~/${REMOTE_SCRIPT}" || true
    fi
  else
    echo "请手动执行："
    echo "  ssh ${SSH_USER}@${NODE_IP}"
    if [[ "$MODE" = "recover" ]]; then
      echo "  bash ~/${REMOTE_SCRIPT} --recover"
    else
      echo "  bash ~/${REMOTE_SCRIPT}"
    fi
  fi

  echo ""
done

echo "=== 说明 ==="
echo "- 挂载点: ${CLIENT_MOUNTPOINT}"
echo "- NFS: ${NFS_SERVER}:${NFS_EXPORT}"
echo "- 若作业出现 0 秒失败且提示 RaisedSignal，优先检查各节点是否出现 Stale file handle；可运行："
echo "  bash $(basename "$0") recover --run"
