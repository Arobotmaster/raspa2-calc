#!/bin/bash
#SBATCH --job-name=418
#SBATCH --nodes=1
export RASPA_TOTAL_CPUS="418"
export RASPA_WORK_DIR="/home/zjp/raspa2-calc/work"
export RASPA_OUTPUT_DIR="wxj-3442-test"
export RASPA_SUBDIR="wxj-3442-test"
export RASPA_WORKER_ID="418"
export RASPA_WORKER_IDS="418"
export RASPA_VERSION="raspa3"
## 单作业=1个进程（RASPA为单线程），每进程仅用1个CPU
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
## 偏好使用超线程（若节点支持会利用，否则自动退化）
#SBATCH --hint=multithread
## 输出与时限
#SBATCH --output=/home/zjp/raspa2-calc/work/wxj-3442-test/1log/418.out
#SBATCH --error=/home/zjp/raspa2-calc/work/wxj-3442-test/1log/418.err
#SBATCH --nodelist=worker-node-03
#SBATCH --time=99999:00:00       ##设置作业的最大运行时间

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

# 设置工作目录 - 优先使用环境变量，其次使用脚本所在目录的父目录，最后智能检测
if [ -n "$RASPA_WORK_DIR" ]; then
    WORK_DIR="$(cd "$RASPA_WORK_DIR" && pwd -P)"
elif [ -d "work" ] && [ -n "$(find "work" -type d -name "mc[0-9]*" ! -name "*__*" 2>/dev/null | head -1)" ]; then
    WORK_DIR="$(pwd -P)"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    WORK_DIR="$(dirname "$SCRIPT_DIR")"
fi

# 根据子目录定位具体执行目录
TARGET_SUBDIR="${RASPA_SUBDIR:-${RASPA_OUTPUT_DIR:-.}}"
if [ -z "$TARGET_SUBDIR" ] || [ "$TARGET_SUBDIR" = "." ]; then
    TARGET_DIR="$WORK_DIR"
else
    TARGET_DIR="$WORK_DIR/$TARGET_SUBDIR"
fi

if ! cd "$TARGET_DIR"; then
    echo "错误：无法切换到工作目录 $TARGET_DIR"
    exit 1
fi

echo "当前工作目录: $(pwd)"
echo "环境变量 RASPA_WORK_DIR: $RASPA_WORK_DIR"
echo "环境变量 RASPA_DIR: $RASPA_DIR"

# 确定工作根目录（优先使用环境变量）
BASE_DIR=""
if [ -n "$RASPA_WORK_DIR" ] && [ -d "$RASPA_WORK_DIR" ]; then
    BASE_DIR="$(cd "$RASPA_WORK_DIR" && pwd -P)"
else
    BASE_DIR="$TARGET_DIR"
    while [ "$BASE_DIR" != "/" ] && [ ! -d "$BASE_DIR/job_templates" ]; do
        BASE_DIR="$(dirname "$BASE_DIR")"
    done
    [ -d "$BASE_DIR/job_templates" ] || BASE_DIR=""
fi
if [ -z "$BASE_DIR" ]; then
    echo "错误：未能确定工作根目录，请设置 RASPA_WORK_DIR"
    exit 1
fi
export RASPA_WORK_DIR="$BASE_DIR"

echo "准备执行 RASPA 模拟任务..."
# 解析核心参数
WORKER_ID=${RASPA_WORKER_ID:-${1:-1}}
TOTAL_CPUS=${RASPA_TOTAL_CPUS:-${2:-1}}
WORKER_IDS_RAW="$(printf '%s' "${RASPA_WORKER_IDS:-}" | tr -d ' \t\r\n\"')"
declare -a WORKER_IDS=()
if [ -n "$WORKER_IDS_RAW" ]; then
  IFS=',' read -r -a WORKER_IDS <<< "$WORKER_IDS_RAW"
fi
if [ ${#WORKER_IDS[@]} -eq 0 ]; then
  WORKER_IDS=("$WORKER_ID")
fi

RUNNER=""
TOOL_DIR="${RASPA_TOOL_DIR:-$HOME/raspa2-calc/.raspa_tools}"
TOOL_TEMPLATES="$TOOL_DIR/job_templates"
RASPA_VERSION_LOWER="$(echo "${RASPA_VERSION:-raspa2}" | tr '[:upper:]' '[:lower:]')"
if [ "$RASPA_VERSION_LOWER" = "raspa3" ] && [ -f "$TOOL_TEMPLATES/runjobs_raspa3.sh" ]; then
  RUNNER="$TOOL_TEMPLATES/runjobs_raspa3.sh"
elif [ -f "$TOOL_TEMPLATES/runjobs.sh" ]; then
  RUNNER="$TOOL_TEMPLATES/runjobs.sh"
elif [ -f "$BASE_DIR/job_templates/runjobs.sh" ]; then
  RUNNER="$BASE_DIR/job_templates/runjobs.sh"
fi
if [ -z "$RUNNER" ]; then
  echo "错误：未找到 runjobs 脚本，请检查 RASPA_TOOL_DIR"
  exit 1
fi

if [ "${RASPA_SIMPLE_LAUNCH:-false}" = "true" ]; then
  if [ ${#WORKER_IDS[@]} -le 1 ]; then
    exec bash "$RUNNER" "$WORKER_ID" "$TOTAL_CPUS"
  fi
  fail=0
  pids=()
  for wid in "${WORKER_IDS[@]}"; do
    [ -n "$wid" ] || continue
    RASPA_WORKER_ID="$wid" bash "$RUNNER" "$wid" "$TOTAL_CPUS" &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
  done
  exit "$fail"
else
  # 用 srun 启动单任务步骤（去掉 cpu-bind 以兼容不支持绑定的集群）
  if [ ${#WORKER_IDS[@]} -le 1 ]; then
    srun --ntasks=1 --cpus-per-task=1 --hint=multithread \
      bash "$RUNNER" "$WORKER_ID" "$TOTAL_CPUS"
    exit $?
  fi
  fail=0
  pids=()
  for wid in "${WORKER_IDS[@]}"; do
    [ -n "$wid" ] || continue
    # 注意：本集群为 SelectTypeParameters=CR_CORE 时，多个 srun step 可能会按“物理核”串行分配资源，
    # 导致同一作业内无法并发跑满超线程。这里直接在 batch step 中后台启动多个 worker（继承作业分配的 CPU 集合）。
    RASPA_WORKER_ID="$wid" bash "$RUNNER" "$wid" "$TOTAL_CPUS" &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
  done
  exit "$fail"
fi
