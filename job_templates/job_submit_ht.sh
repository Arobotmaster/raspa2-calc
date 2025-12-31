#!/bin/bash
#SBATCH --job-name=2
#SBATCH --nodes=1
export RASPA_TOTAL_CPUS="2"
export RASPA_WORK_DIR="/home/zjp/raspa2-calc/work"
export RASPA_OUTPUT_DIR="1pymser"
export RASPA_SUBDIR="1pymser"
export RASPA_WORKER_ID="2"
export RASPA_VERSION="raspa3"
## 单作业=1个进程（RASPA为单线程），每进程仅用1个CPU
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
## 偏好使用超线程（若节点支持会利用，否则自动退化）
#SBATCH --hint=multithread
## 输出与时限
#SBATCH --output=/home/zjp/raspa2-calc/work/1pymser/1log/2.out
#SBATCH --error=/home/zjp/raspa2-calc/work/1pymser/1log/2.err
#SBATCH --nodelist=worker-node-02
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

# 确定包含 job_templates 的根目录
BASE_DIR="$TARGET_DIR"
while [ "$BASE_DIR" != "/" ] && [ ! -d "$BASE_DIR/job_templates" ]; do
    BASE_DIR="$(dirname "$BASE_DIR")"
done
if [ ! -d "$BASE_DIR/job_templates" ]; then
    echo "错误：未找到 job_templates 目录"
    exit 1
fi
export RASPA_WORK_DIR="$BASE_DIR"

echo "准备执行 RASPA 模拟任务..."
# 解析核心参数
WORKER_ID=${RASPA_WORKER_ID:-${1:-1}}
TOTAL_CPUS=${RASPA_TOTAL_CPUS:-${2:-1}}

RUNNER="$BASE_DIR/job_templates/runjobs.sh"

if [ "${RASPA_SIMPLE_LAUNCH:-false}" = "true" ]; then
  exec bash "$RUNNER" "$WORKER_ID" "$TOTAL_CPUS"
else
  # 用 srun 启动单任务步骤（去掉 cpu-bind 以兼容不支持绑定的集群）
  srun --ntasks=1 --cpus-per-task=1 --hint=multithread \
    bash "$RUNNER" "$WORKER_ID" "$TOTAL_CPUS"
fi
