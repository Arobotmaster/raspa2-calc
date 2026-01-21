#!/bin/bash
#SBATCH --job-name=raspa_job
#SBATCH --nodes=1
## 单作业=1个进程（RASPA为单线程），每进程仅用1个CPU
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
## 偏好使用超线程（若节点支持会利用，否则自动退化）
#SBATCH --hint=multithread
## 输出与时限
#SBATCH --output=raspa_job.out
#SBATCH --error=raspa_job.err
# #SBATCH --nodelist=worker-node-03  # 注释掉节点限制，允许调度器自动分配
#SBATCH --time=99999:00:00       ##设置作业的最大运行时间

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

## 通过 srun 运行任务处理器，保证单任务步骤与绑核策略，simulate 在其中直接调用
BASE_DIR="${RASPA_WORK_DIR:-$(pwd -P)}"
TOOL_DIR="${RASPA_TOOL_DIR:-$HOME/raspa2-calc/.raspa_tools}"
TOOL_TEMPLATES="$TOOL_DIR/job_templates"
RASPA_VERSION_LOWER="$(echo "${RASPA_VERSION:-raspa2}" | tr '[:upper:]' '[:lower:]')"
if [ "$RASPA_VERSION_LOWER" = "raspa3" ] && [ -f "$TOOL_TEMPLATES/runjobs_raspa3.sh" ]; then
  RUNNER="$TOOL_TEMPLATES/runjobs_raspa3.sh"
elif [ -f "$TOOL_TEMPLATES/runjobs.sh" ]; then
  RUNNER="$TOOL_TEMPLATES/runjobs.sh"
else
  RUNNER="$BASE_DIR/job_templates/runjobs.sh"
fi
if [ ! -f "$RUNNER" ]; then
  echo "错误: 未找到 runjobs 脚本，请检查 RASPA_TOOL_DIR"
  exit 1
fi
srun --ntasks=1 --cpus-per-task=1 --hint=multithread --cpu-bind=threads \
  bash "$RUNNER" "$1" "$2"
