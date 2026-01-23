#!/bin/bash

# 设置环境变量，避免数学库的线程冲突
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

# 清除可能会干扰的PYTHONPATH环境变量
if [ -n "$PYTHONPATH" ]; then
    unset PYTHONPATH
fi

# 获取工具安装目录
TOOL_DIR="$HOME/raspa2-calc/.raspa_tools"
# 获取当前工作目录（从环境变量）
WORK_DIR="$RASPA_WORK_DIR"

# 检查作业调度系统类型（SLURM or PBS），但传递小写参数
JOB_SYSTEM="local"
if command -v sbatch >/dev/null 2>&1; then
    JOB_SYSTEM="slurm"
    echo "检测到SLURM作业调度系统"
elif command -v qsub >/dev/null 2>&1; then
    JOB_SYSTEM="pbs"
    echo "检测到PBS作业调度系统"
else
    echo "未检测到SLURM或PBS作业调度系统，将使用本地模式运行"
fi

# 检查Python环境
PYTHON_CMD=""
for cmd in python3 python python3.11 python3.10 python3.9 python3.8 python3.7 python3.6; do
    if command -v $cmd &> /dev/null; then
        PYTHON_CMD=$cmd
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "错误：找不到Python命令。请安装Python 3.6+"
    exit 1
fi

# 检查必要的Python包
$PYTHON_CMD -c "import pandas; import numpy" 2>/dev/null || {
    echo "错误：缺少必要的Python包。请安装以下包："
    echo "pip install pandas numpy"
    echo "或者创建一个新的conda环境："
    echo "conda create -n raspa2 python=3.11 pandas numpy"
    echo "conda activate raspa2"
    exit 1
}

echo "=== RASPA参数筛选工具 ==="
echo "作业系统: $JOB_SYSTEM"
echo "Python: $($PYTHON_CMD --version)"

# 调用Python模块进行参数筛选
$PYTHON_CMD -m raspa_calc.tools.parameter_screening --job-system "$JOB_SYSTEM" "$@"

# 退出
exit $?
