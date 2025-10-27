#!/bin/bash

# 获取工具安装目录
TOOL_DIR="$HOME/raspa2-calc/.raspa_tools"
# 获取当前工作目录
WORK_DIR="$PWD"

# 设置工作目录环境变量
export RASPA_WORK_DIR="$WORK_DIR"

# 调用Python主程序，传递所有参数
exec python "$TOOL_DIR/scripts/python/raspa_calc.py" "$@"
