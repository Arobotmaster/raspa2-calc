#!/bin/bash
#PBS -N raspa_job
#PBS -l nodes=1:ppn=1
#PBS -o raspa_job.out
#PBS -e raspa_job.err
#PBS -V

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1 
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

# 设置工作目录 - 优先使用环境变量，其次使用脚本所在目录的父目录
if [ -n "$RASPA_WORK_DIR" ]; then
    WORK_DIR="$RASPA_WORK_DIR"
else
    # 获取脚本所在目录的父目录作为默认工作目录
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    WORK_DIR="$(dirname "$SCRIPT_DIR")"
fi

if ! cd "$WORK_DIR"; then
    echo "错误：无法切换到工作目录 $WORK_DIR"
    exit 1
fi

# 检查是否存在simulation.input文件
if [ ! -f "simulation.input" ]; then
    echo "错误: 当前目录中未找到simulation.input文件"
    echo "当前目录: $(pwd)"
    ls -la
    exit 1
fi

echo "找到simulation.input文件，开始执行RASPA模拟..."

# 解析并传递工人编号与总并发数（与SLURM保持一致的接口）
WORKER_ID=${RASPA_WORKER_ID:-1}
TOTAL_CPUS=${RASPA_TOTAL_CPUS:-1}

# 优先使用 bash 执行，确保环境变量与管道行为一致
TOOL_DIR="${RASPA_TOOL_DIR:-$HOME/raspa2-calc/.raspa_tools}"
TOOL_TEMPLATES="$TOOL_DIR/job_templates"
RASPA_VERSION_LOWER="$(echo "${RASPA_VERSION:-raspa2}" | tr '[:upper:]' '[:lower:]')"
if [ "$RASPA_VERSION_LOWER" = "raspa3" ] && [ -f "$TOOL_TEMPLATES/runjobs_raspa3.sh" ]; then
    RUNNER="$TOOL_TEMPLATES/runjobs_raspa3.sh"
elif [ -f "$TOOL_TEMPLATES/runjobs.sh" ]; then
    RUNNER="$TOOL_TEMPLATES/runjobs.sh"
else
    RUNNER="$WORK_DIR/job_templates/runjobs.sh"
fi
if [ ! -f "$RUNNER" ]; then
    echo "错误: 未找到 runjobs 脚本，请检查 RASPA_TOOL_DIR"
    exit 1
fi
bash "$RUNNER" "$WORKER_ID" "$TOTAL_CPUS"
