#!/bin/bash
# NFS 客户端配置/修复脚本
# - 首次配置：挂载 + 写入 /etc/fstab
# - 故障修复：当出现 "Stale file handle" 时，执行 lazy+force umount 后再 mount -a

set -euo pipefail

usage() {
  cat <<'EOF'
用法: nfs_client_setup.sh [选项]

选项:
  --recover            发现挂载异常/或强制执行重挂载（修复 Stale file handle）
  --restart-slurmd     修复挂载后重启 slurmd（建议仅在控制节点/无作业运行时使用）
  --no-fstab           不写入 /etc/fstab
  -h, --help           显示帮助

环境变量（可选）:
  NFS_SERVER   默认 10.10.14.12
  NFS_EXPORT   默认 /shared/raspa2-calc
  MOUNTPOINT   默认 /home/zjp/raspa2-calc
  WORK_DIR     默认 ${MOUNTPOINT}/work（RASPA_WORK_DIR 写入该路径）
EOF
}

RECOVER=0
RESTART_SLURMD=0
NO_FSTAB=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --recover) RECOVER=1 ;;
    --restart-slurmd) RESTART_SLURMD=1 ;;
    --no-fstab) NO_FSTAB=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1"; usage; exit 2 ;;
  esac
  shift
done

echo "=== 配置/修复 NFS 客户端 ==="

NFS_SERVER="${NFS_SERVER:-10.10.14.12}"
NFS_EXPORT="${NFS_EXPORT:-/shared/raspa2-calc}"
MOUNTPOINT="${MOUNTPOINT:-/home/zjp/raspa2-calc}"
WORK_DIR="${WORK_DIR:-${MOUNTPOINT}/work}"

is_mounted() {
  grep -qsE "^[^ ]+ ${MOUNTPOINT} " /proc/mounts
}

is_healthy() {
  ls -ld "${MOUNTPOINT}" >/dev/null 2>&1
}

# 检查 nfs-utils 是否已安装（Rocky/Alma/RHEL）
if ! rpm -qa | grep -q '^nfs-utils'; then
  echo "安装 NFS 客户端工具(nfs-utils)..."
  sudo yum install -y nfs-utils --disablerepo=epel,docker-ce-stable
fi

echo "创建挂载点: ${MOUNTPOINT}"
sudo mkdir -p "${MOUNTPOINT}"

echo "检查 NFS export（可选）: ${NFS_SERVER}:${NFS_EXPORT}"
showmount -e "${NFS_SERVER}" >/dev/null 2>&1 || true

if is_mounted; then
  if [[ "${RECOVER}" = "1" ]] || ! is_healthy; then
    echo "检测到挂载异常/需要恢复，执行重挂载（可能修复 Stale file handle）..."
    sudo umount -fl "${MOUNTPOINT}" || sudo umount -l "${MOUNTPOINT}" || true
  else
    echo "已挂载且状态正常，跳过重挂载。"
  fi
fi

if ! is_mounted; then
  echo "挂载 NFS: ${NFS_SERVER}:${NFS_EXPORT} -> ${MOUNTPOINT}"
  sudo mount -t nfs4 "${NFS_SERVER}:${NFS_EXPORT}" "${MOUNTPOINT}"
fi

if ! is_healthy; then
  echo "❌ 挂载后仍无法访问: ${MOUNTPOINT}"
  echo "   可能仍是 Stale file handle 或服务端 export 异常。"
  echo "   建议：在该节点执行 sudo umount -fl ${MOUNTPOINT} && sudo mount -a"
  exit 1
fi

# 创建默认工作目录（位于 NFS 共享内）
mkdir -p "${WORK_DIR}" || true

if [[ "${NO_FSTAB}" != "1" ]]; then
  # 添加到 /etc/fstab（避免重复写入）
  if ! grep -qsE "^${NFS_SERVER}:${NFS_EXPORT}[[:space:]]+${MOUNTPOINT}[[:space:]]" /etc/fstab; then
    echo "写入 /etc/fstab 以便开机自动挂载..."
    echo "${NFS_SERVER}:${NFS_EXPORT} ${MOUNTPOINT} nfs4 defaults,_netdev,hard,timeo=600,retrans=2 0 0" | sudo tee -a /etc/fstab >/dev/null
  fi
fi

# 设置环境变量（写入/更新 ~/.bashrc）
if [[ -f ~/.bashrc ]] && grep -qE '^[[:space:]]*export[[:space:]]+RASPA_WORK_DIR=' ~/.bashrc 2>/dev/null; then
  if ! grep -qF "export RASPA_WORK_DIR=${WORK_DIR}" ~/.bashrc 2>/dev/null; then
    echo "更新 ~/.bashrc: RASPA_WORK_DIR -> ${WORK_DIR}"
    sed -i -E "s|^[[:space:]]*export[[:space:]]+RASPA_WORK_DIR=.*$|export RASPA_WORK_DIR=${WORK_DIR}|g" ~/.bashrc
  fi
else
  echo "写入 ~/.bashrc 环境变量..."
  echo "export RASPA_WORK_DIR=${WORK_DIR}" >> ~/.bashrc
fi

if [[ -f ~/.bashrc ]] && grep -qE '^[[:space:]]*export[[:space:]]+RASPA_DIR=' ~/.bashrc 2>/dev/null; then
  if ! grep -qF 'export RASPA_DIR=/home/zjp/anaconda3/pkgs/raspa2-2.0.50-h678ec8c_0' ~/.bashrc 2>/dev/null; then
    echo "更新 ~/.bashrc: RASPA_DIR"
    sed -i -E "s|^[[:space:]]*export[[:space:]]+RASPA_DIR=.*$|export RASPA_DIR=/home/zjp/anaconda3/pkgs/raspa2-2.0.50-h678ec8c_0|g" ~/.bashrc
  fi
else
  echo 'export RASPA_DIR=/home/zjp/anaconda3/pkgs/raspa2-2.0.50-h678ec8c_0' >> ~/.bashrc
fi

if [[ "${RESTART_SLURMD}" = "1" ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    echo "重启 slurmd（谨慎：计算节点有作业在跑时不建议）..."
    sudo systemctl restart slurmd || true
  fi
fi

echo "验证挂载状态..."
df -h "${MOUNTPOINT}" || true
ls -la "${MOUNTPOINT}" | head

echo "✅ NFS客户端配置完成"
