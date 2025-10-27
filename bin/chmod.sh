#!/bin/bash

# 获取工具安装目录
TOOL_DIR="$HOME/raspa2-calc/.raspa_tools"
# 获取当前工作目录（从环境变量）
WORK_DIR="$RASPA_WORK_DIR"

# 检查参数
if [ $# -ne 2 ]; then
    echo "错误：需要CSV文件路径和列号作为参数"
    exit 1
fi

csv_file="$1"
column_number="$2"

# 设置错误处理
set -e  # 当命令返回非零状态时立即退出

# CIF文件目录现在通过配置文件指定，不再检查固定的data/cif目录

# 创建其他必要的工作目录（不包括data目录）
mkdir -p "$WORK_DIR"/{job_templates,results,logs}

# 复制必要文件到工作目录
cp "$TOOL_DIR/job_templates/tasksrun.sh" "$WORK_DIR/job_templates/"
cp "$TOOL_DIR/job_templates/runjobs.sh" "$WORK_DIR/job_templates/"
cp "$TOOL_DIR/job_templates/pbs.sh" "$WORK_DIR/job_templates/" 2>/dev/null || echo "警告: pbs.sh 文件不存在"
cp "$TOOL_DIR/job_templates/sbatch.sh" "$WORK_DIR/job_templates/" 2>/dev/null || echo "警告: sbatch.sh 文件不存在"
cp "$TOOL_DIR/job_templates/local.sh" "$WORK_DIR/job_templates/" 2>/dev/null || echo "警告: local.sh 文件不存在"

# 给予必要文件执行权限
chmod 755 "$WORK_DIR/job_templates/tasksrun.sh" 2>/dev/null || true
chmod 755 "$WORK_DIR/job_templates/runjobs.sh" 2>/dev/null || true
chmod 755 "$WORK_DIR/job_templates/pbs.sh" 2>/dev/null || true
chmod 755 "$WORK_DIR/job_templates/sbatch.sh" 2>/dev/null || true
chmod 755 "$WORK_DIR/job_templates/local.sh" 2>/dev/null || true
chmod 755 "$WORK_DIR/job_templates/job_submit_ht.sh" 2>/dev/null || true
chmod 755 "$WORK_DIR/job_templates/job_submit.sh" 2>/dev/null || true

# 确保工具目录中的脚本也有执行权限
chmod 755 "$TOOL_DIR/job_templates/tasksrun.sh" 2>/dev/null || true
chmod 755 "$TOOL_DIR/job_templates/runjobs.sh" 2>/dev/null || true

# 检查RASPA_DIR环境变量是否设置
if [ -z "$RASPA_DIR" ]; then
    echo "警告：RASPA_DIR环境变量未设置"
    echo "请输入RASPA安装目录的路径（例如：/opt/raspa）："
    read raspa_dir
    if [ -z "$raspa_dir" ]; then
        echo "错误：未提供RASPA安装目录，无法继续"
        exit 1
    fi
    # 检查目录是否存在
    if [ ! -d "$raspa_dir" ]; then
        echo "错误：目录 $raspa_dir 不存在"
        exit 1
    fi
    # 检查simulate程序是否存在
    if [ ! -f "$raspa_dir/bin/simulate" ]; then
        echo "错误：未在 $raspa_dir/bin 中找到simulate程序"
        exit 1
    fi
    # 设置环境变量
    export RASPA_DIR="$raspa_dir"
    echo "已设置RASPA_DIR=$RASPA_DIR"
fi

echo "启动RASPA高通量计算设置..."
# 运行Python脚本并捕获返回值
cd "$WORK_DIR"  # 切换到工作目录
python "$TOOL_DIR/scripts/python/task_runner.py" "$csv_file" "$column_number" || {
    # 直接捕获Python脚本的退出
    status=$?
    echo "RASPA设置程序被中断或遇到错误（退出代码: $status），停止执行"
    exit $status
}

# 如果Python脚本成功完成，才会执行到这里
echo "RASPA设置成功完成，准备提交计算任务..."

# 直接传递用户之前设置的CPU核心数
echo ""
echo "=== 任务提交配置 ==="
echo "每个RASPA任务使用1个CPU核心，提交多个独立作业来并行计算"

# 从runjobs.sh读取用户之前配置的CPU核心数
runjobs_file="$WORK_DIR/job_templates/runjobs.sh"
if [ -f "$runjobs_file" ]; then
    # 正确解析参数，处理动态赋值和纯数值两种情况
    max_line=$(grep "^MAX=" "$runjobs_file")
    step_line=$(grep "^STEP=" "$runjobs_file")
    
    # 检查是否是纯数值（已更新）还是动态计算（未更新）
    if [[ "$step_line" =~ ^STEP=[0-9]+[[:space:]]+# ]]; then
        # 已更新的纯数值格式: STEP=100           # CPU核心数
        step_tasks=$(echo "$step_line" | sed 's/^STEP=\([0-9]*\)[[:space:]].*/\1/')
        max_tasks=$(echo "$max_line" | sed 's/^MAX=\([0-9]*\)[[:space:]].*/\1/' 2>/dev/null || echo "未知")
        echo "检测到任务参数: 总任务数=$max_tasks, 用户设置核心数=$step_tasks"
        echo "直接使用用户之前配置的CPU核心数: $step_tasks"
        cpu_cores=$step_tasks
    else
        # 原始动态格式: STEP=${CPU:-2} - 未配置的情况
        echo "警告：未检测到用户配置的CPU核心数，请先运行计算设置"
        echo "建议先运行 chmod.sh 进行任务配置"
        exit 1
    fi
else
    echo "错误：未找到 runjobs.sh 文件，请先运行计算设置"
    exit 1
fi

echo "将使用 $cpu_cores 个CPU核心提交任务"

# 最终确保tasksrun.sh有执行权限
chmod 755 "$WORK_DIR/job_templates/tasksrun.sh"
chmod 755 "$WORK_DIR/job_templates/runjobs.sh"

# 验证关键文件权限设置
if [ ! -x "$WORK_DIR/job_templates/tasksrun.sh" ]; then
    echo "错误：tasksrun.sh 没有执行权限"
    ls -la "$WORK_DIR/job_templates/tasksrun.sh"
    exit 1
fi

echo "检查job_templates目录中的文件："
ls -la "$WORK_DIR/job_templates/"

# 仅当Python脚本成功时才执行tasksrun.sh，并传递CPU核心数
echo "执行tasksrun.sh，使用CPU核心数: $cpu_cores"
"$WORK_DIR/job_templates/tasksrun.sh" "$cpu_cores"