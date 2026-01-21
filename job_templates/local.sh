#!/bin/bash
# 本地执行模式 - 无作业调度系统环境下使用

# 设置作业名称
JOB_NAME="local_job"
echo "开始执行本地作业"

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

# 记录开始时间
START_TIME=$(date +%s)
echo "作业开始时间: $(date)"

# 执行runjobs.sh脚本
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
sh "$RUNNER" "$1" "$2"

# 记录结束时间和运行时长
END_TIME=$(date +%s)
RUNTIME=$((END_TIME - START_TIME))
echo "作业结束时间: $(date)"
echo "总运行时间: $RUNTIME 秒"

# 检查是否成功完成
if [ $? -eq 0 ]; then
    echo "作业成功完成"
    exit 0
else
    echo "作业失败"
    exit 1
fi 
