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
# 执行runjobs.sh脚本，允许指定job_templates/runjobs.sh的完整路径
sh job_templates/runjobs.sh $1 $2 