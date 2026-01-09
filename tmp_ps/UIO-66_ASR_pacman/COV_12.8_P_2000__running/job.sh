#!/bin/bash

# 设置环境变量
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
MSER_ENABLED=0


# 初始化 conda
if [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
fi

# 激活 RASPA3 环境
conda activate raspa3

# 切换到作业目录
ORIG_DIR="/home/zjp/raspa2-calc/.raspa_tools/tmp_ps/UIO-66_ASR_pacman/COV_12.8_P_2000"
PARENT_DIR="$(dirname "$ORIG_DIR")"
BASE_DIR="$(basename "$ORIG_DIR")"
RUN_DIR="$ORIG_DIR"
if [ -d "${ORIG_DIR}__running" ]; then RUN_DIR="${ORIG_DIR}__running"; fi
if [ -d "${ORIG_DIR}__done" ]; then RUN_DIR="${ORIG_DIR}__done"; fi
if [ -d "${ORIG_DIR}__failed" ]; then RUN_DIR="${ORIG_DIR}__failed"; fi
if [ "$RUN_DIR" = "$ORIG_DIR" ] && [ -d "$ORIG_DIR" ]; then
  (cd "$PARENT_DIR" && mv "$BASE_DIR" "${BASE_DIR}__running") && RUN_DIR="${ORIG_DIR}__running"
fi
cd "$RUN_DIR" || exit 1

echo $$ > jobid
echo "running" > "status.txt"

# 运行 RASPA3
raspa3_exit_code=0
mser_status=0
raspa3
raspa3_exit_code=$?

if [ $raspa3_exit_code -ne 0 ]; then
    echo "failed_simulate" > "status.txt"
    mv "$RUN_DIR" "${ORIG_DIR}__failed" 2>/dev/null || true
elif [ $MSER_ENABLED -eq 1 ] && [ $mser_status -ne 0 ]; then
    echo "failed_mser" > "status.txt"
    mv "$RUN_DIR" "${ORIG_DIR}__failed" 2>/dev/null || true
else
    echo "done" > "status.txt"
    mv "$RUN_DIR" "${ORIG_DIR}__done" 2>/dev/null || true
fi
