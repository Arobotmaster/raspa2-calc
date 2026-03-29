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
  NFS_MOUNT_OPTS 自定义挂载参数（默认自动含 nconnect=4 + noatime/nodiratime）
  NFS_WORK_EXPORT  单独为 work 目录挂载的 NFS 路径（例如 /srv/raspa2-calc-work）
  NFS_WORK_MOUNT   work 目录挂载点（默认 ${MOUNTPOINT}/work）
  NFS_WORK_OPTS    work 目录挂载参数（默认与 NFS_MOUNT_OPTS 一致）
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
NFS_EXPORT="${NFS_EXPORT:-/srv/raspa2-calc}"
MOUNTPOINT="${MOUNTPOINT:-/home/zjp/raspa2-calc}"
WORK_DIR="${WORK_DIR:-${MOUNTPOINT}/work}"
# work 目录使用 Mount Overlay：挂载到 /srv/raspa2-calc-work，覆盖 /srv/raspa2-calc 下的空 work 子目录
NFS_WORK_EXPORT="${NFS_WORK_EXPORT:-/srv/raspa2-calc-work}"
NFS_WORK_MOUNT="${NFS_WORK_MOUNT:-${MOUNTPOINT}/work}"
DEFAULT_MOUNT_OPTS="rw,relatime,vers=4.2,rsize=1048576,wsize=1048576,namlen=255,hard,proto=tcp,timeo=600,retrans=2,sec=sys,local_lock=none,noatime,nodiratime"
MOUNT_OPTS_PREFERRED="${DEFAULT_MOUNT_OPTS},nconnect=4"
MOUNT_OPTS_FINAL=""

is_mounted() {
  grep -qsE "^[^ ]+ ${MOUNTPOINT} " /proc/mounts
}

is_work_mounted() {
  grep -qsE "^[^ ]+ ${NFS_WORK_MOUNT} " /proc/mounts
}

is_work_healthy() {
  timeout 2 ls -ld "${NFS_WORK_MOUNT}" >/dev/null 2>&1
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
    # 同时处理 work 目录的 overlay 挂载
    if is_work_mounted || [[ -n "${NFS_WORK_EXPORT}" ]]; then
      echo "  同步处理 work 目录挂载..."
      sudo umount -fl "${NFS_WORK_MOUNT}" || sudo umount -l "${NFS_WORK_MOUNT}" || true
    fi
  else
    echo "已挂载且状态正常，跳过重挂载。"
    # 即使主挂载健康，也检查 work 目录是否缺失 overlay
    if [[ -n "${NFS_WORK_EXPORT}" ]] && ! is_work_mounted; then
      echo "  [警告] work 目录挂载缺失，将重新挂载..."
      sudo mkdir -p "${NFS_WORK_MOUNT}"
      sudo mount -t nfs4 -o "${DEFAULT_MOUNT_OPTS}" \
        "${NFS_SERVER}:${NFS_WORK_EXPORT}" "${NFS_WORK_MOUNT}" || true
    fi
  fi
fi

if ! is_mounted; then
  echo "挂载 NFS: ${NFS_SERVER}:${NFS_EXPORT} -> ${MOUNTPOINT}"
  if [ -n "${NFS_MOUNT_OPTS:-}" ]; then
    MOUNT_OPTS_FINAL="${NFS_MOUNT_OPTS}"
    sudo mount -t nfs4 -o "${MOUNT_OPTS_FINAL}" "${NFS_SERVER}:${NFS_EXPORT}" "${MOUNTPOINT}"
  else
    if sudo mount -t nfs4 -o "${MOUNT_OPTS_PREFERRED}" "${NFS_SERVER}:${NFS_EXPORT}" "${MOUNTPOINT}"; then
      MOUNT_OPTS_FINAL="${MOUNT_OPTS_PREFERRED}"
    else
      echo "挂载失败，尝试去掉 nconnect 选项重试..."
      sudo mount -t nfs4 -o "${DEFAULT_MOUNT_OPTS}" "${NFS_SERVER}:${NFS_EXPORT}" "${MOUNTPOINT}"
      MOUNT_OPTS_FINAL="${DEFAULT_MOUNT_OPTS}"
    fi
  fi
else
  MOUNT_OPTS_FINAL="${NFS_MOUNT_OPTS:-${MOUNT_OPTS_PREFERRED}}"
fi

if ! is_healthy; then
  echo "❌ 挂载后仍无法访问: ${MOUNTPOINT}"
  echo "   可能仍是 Stale file handle 或服务端 export 异常。"
  echo "   建议：在该节点执行 sudo umount -fl ${MOUNTPOINT} && sudo mount -a"
  exit 1
fi

# 创建默认工作目录（位于 NFS 共享内）
mkdir -p "${WORK_DIR}" || true

# 可选：为 work 目录单独挂载到 NVMe NFS（提高高频读写性能）
if [ -n "$NFS_WORK_EXPORT" ]; then
  echo "检测到 NFS_WORK_EXPORT=${NFS_WORK_EXPORT}，准备挂载 work 目录..."
  sudo mkdir -p "${NFS_WORK_MOUNT}"
  WORK_MOUNT_OPTS="${NFS_WORK_OPTS:-${MOUNT_OPTS_FINAL:-${MOUNT_OPTS_PREFERRED}}}"
  if grep -qsE "^[^ ]+ ${NFS_WORK_MOUNT} " /proc/mounts; then
    if ! sudo mount -o remount,"${WORK_MOUNT_OPTS}" "${NFS_WORK_MOUNT}"; then
      if echo "$WORK_MOUNT_OPTS" | grep -q "nconnect="; then
        echo "work 目录 remount 失败，尝试去掉 nconnect 重试..."
        sudo mount -o remount,"${DEFAULT_MOUNT_OPTS}" "${NFS_WORK_MOUNT}" || true
        WORK_MOUNT_OPTS="${DEFAULT_MOUNT_OPTS}"
      fi
    fi
  else
    if ! sudo mount -t nfs4 -o "${WORK_MOUNT_OPTS}" "${NFS_SERVER}:${NFS_WORK_EXPORT}" "${NFS_WORK_MOUNT}"; then
      if echo "$WORK_MOUNT_OPTS" | grep -q "nconnect="; then
        echo "work 目录挂载失败，尝试去掉 nconnect 重试..."
        if sudo mount -t nfs4 -o "${DEFAULT_MOUNT_OPTS}" "${NFS_SERVER}:${NFS_WORK_EXPORT}" "${NFS_WORK_MOUNT}"; then
          WORK_MOUNT_OPTS="${DEFAULT_MOUNT_OPTS}"
        else
          echo "❌ work 目录挂载失败: ${NFS_SERVER}:${NFS_WORK_EXPORT} -> ${NFS_WORK_MOUNT}"
          exit 1
        fi
      else
        echo "❌ work 目录挂载失败: ${NFS_SERVER}:${NFS_WORK_EXPORT} -> ${NFS_WORK_MOUNT}"
        exit 1
      fi
    fi
  fi
fi

if [[ "${NO_FSTAB}" != "1" ]]; then
  # 添加到 /etc/fstab（避免重复写入）
  if [ -z "${MOUNT_OPTS_FINAL}" ]; then
    MOUNT_OPTS_FINAL="${NFS_MOUNT_OPTS:-${MOUNT_OPTS_PREFERRED}}"
  fi
  if grep -qsE "^${NFS_SERVER}:${NFS_EXPORT}[[:space:]]+${MOUNTPOINT}[[:space:]]" /etc/fstab; then
    echo "更新 /etc/fstab 挂载参数..."
    TMP_FSTAB=$(mktemp)
    python3 - "$NFS_SERVER" "$NFS_EXPORT" "$MOUNTPOINT" "$MOUNT_OPTS_FINAL" "$TMP_FSTAB" >/dev/null <<'PY'
import sys

server = sys.argv[1]
export = sys.argv[2]
mnt = sys.argv[3]
opts = sys.argv[4]

target = f"{server}:{export} {mnt} nfs4 {opts},_netdev 0 0"
out = []
with open("/etc/fstab", "r", encoding="utf-8") as fh:
    for raw in fh:
        line = raw.rstrip("\n")
        if line.strip().startswith("#") or not line.strip():
            out.append(raw)
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] == f"{server}:{export}" and parts[1] == mnt:
            out.append(target + "\n")
        else:
            out.append(raw)

with open(sys.argv[5], "w", encoding="utf-8") as fh:
    fh.writelines(out)
PY
    sudo cp -f "$TMP_FSTAB" /etc/fstab
    rm -f "$TMP_FSTAB" || true
  else
    echo "写入 /etc/fstab 以便开机自动挂载..."
    echo "${NFS_SERVER}:${NFS_EXPORT} ${MOUNTPOINT} nfs4 ${MOUNT_OPTS_FINAL},_netdev 0 0" | sudo tee -a /etc/fstab >/dev/null
  fi
  if [ -n "$NFS_WORK_EXPORT" ]; then
    WORK_MOUNT_OPTS="${NFS_WORK_OPTS:-${MOUNT_OPTS_FINAL}}"
    if grep -qsE "^[^ ]+ ${NFS_WORK_MOUNT}[[:space:]]" /etc/fstab; then
      echo "更新 /etc/fstab work 目录挂载参数..."
      TMP_FSTAB=$(mktemp)
      python3 - "$NFS_SERVER" "$NFS_WORK_EXPORT" "$NFS_WORK_MOUNT" "$WORK_MOUNT_OPTS" "$TMP_FSTAB" >/dev/null <<'PY'
import sys

server = sys.argv[1]
export = sys.argv[2]
mnt = sys.argv[3]
opts = sys.argv[4]
tmp_path = sys.argv[5]

target = f"{server}:{export} {mnt} nfs4 {opts},_netdev 0 0"
out = []
with open("/etc/fstab", "r", encoding="utf-8") as fh:
    for raw in fh:
        line = raw.rstrip("\n")
        if line.strip().startswith("#") or not line.strip():
            out.append(raw)
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] == f"{server}:{export}" and parts[1] == mnt:
            out.append(target + "\n")
        else:
            out.append(raw)

with open(tmp_path, "w", encoding="utf-8") as fh:
    fh.writelines(out)
PY
      sudo cp -f "$TMP_FSTAB" /etc/fstab
      rm -f "$TMP_FSTAB" || true
    else
      echo "写入 /etc/fstab work 目录挂载条目..."
      echo "${NFS_SERVER}:${NFS_WORK_EXPORT} ${NFS_WORK_MOUNT} nfs4 ${WORK_MOUNT_OPTS},_netdev 0 0" | sudo tee -a /etc/fstab >/dev/null
    fi
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
