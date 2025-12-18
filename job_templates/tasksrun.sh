#!/bin/bash 

# 获取工具安装目录 - 优先使用环境变量
if [ -n "$RASPA_WORK_DIR" ]; then
    TOOL_DIR="$RASPA_WORK_DIR/.raspa_tools"
else
    # 获取脚本所在目录的父目录
    SCRIPT_DIR_BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PARENT_DIR="$(dirname "$SCRIPT_DIR_BASE")"
    TOOL_DIR="$PARENT_DIR/.raspa_tools"
fi
# 获取当前工作目录（从环境变量）
WORK_DIR="$RASPA_WORK_DIR"

# 设置顶部目录为当前工作目录（规范化去除 /./ 等）
if [ -n "$WORK_DIR" ]; then
    topdir="$(cd "$WORK_DIR" && pwd -P)"
else
    topdir="$(pwd -P)"
fi
WORK_DIR="$topdir"

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 给予所有脚本执行权限
find "$SCRIPT_DIR" -type f -name "*.sh" -exec chmod 755 {} \;

# 检查RASPA_DIR是否设置
if [ -z "$RASPA_DIR" ]; then
    echo "错误：RASPA_DIR环境变量未设置"
    echo "请设置RASPA_DIR环境变量指向RASPA安装目录"
    exit 1
fi

# 获取CPU核心数参数，默认为2
CPU_CORES=${1:-2}
fname="mc"  # 固定使用mc前缀

echo "开始提交计算任务..."
echo "使用CPU核心数: $CPU_CORES"

# 智能检测子目录
detect_subdir() {
    # 优先使用环境/配置指定的子目录
    if [ -n "$RASPA_SUBDIR" ] && [ -d "$topdir/$RASPA_SUBDIR" ]; then
        echo "$RASPA_SUBDIR"; return
    fi
    if [ -n "$RASPA_OUTPUT_DIR" ] && [ -d "$topdir/$RASPA_OUTPUT_DIR" ]; then
        echo "$RASPA_OUTPUT_DIR"; return
    fi
    # 自动探测：选第一个包含 mc* 的子目录
    local found_subdirs=$(find "$topdir" -maxdepth 2 -type d -name "mc[0-9]*" ! -name "*__*" -print -quit 2>/dev/null)
    if [ -n "$found_subdirs" ]; then
        local d
        d="$(dirname "$found_subdirs")"
        d="${d%/}"
        if [ "$d" = "$topdir" ]; then
            echo "."
        else
            d="${d#${topdir}/}"
            echo "$d"
        fi
    else
        echo "."  # 默认子目录，与 runjobs.sh 保持一致
    fi
}

insert_exports_after_sbatch() {
    local script_path="$1"
    shift || true
    if [ $# -eq 0 ]; then
        return 0
    fi
    python3 - "$script_path" "$@" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
exports = sys.argv[2:]

if not path.exists():
    sys.exit(0)

content = path.read_text(encoding="utf-8").splitlines()
if not content:
    sys.exit(0)

header = [content[0]]
idx = 1
while idx < len(content) and content[idx].startswith("#SBATCH"):
    header.append(content[idx])
    idx += 1

rest = content[idx:]

with path.open("w", encoding="utf-8") as fh:
    for line in header:
        fh.write(line + "\n")
    for exp in exports:
        fh.write(exp + "\n")
    for line in rest:
        fh.write(line + "\n")
PY
}


SUBDIR=$(detect_subdir)
echo "检测到子目录: $SUBDIR"

# 统计总任务数
TOTAL_TASKS=$(find "$topdir/$SUBDIR" -maxdepth 1 -type d -name "mc[0-9]*" ! -name "*__*" 2>/dev/null | wc -l)
echo "检测到总任务数: $TOTAL_TASKS"

if [ $TOTAL_TASKS -eq 0 ]; then
    echo "警告：未找到待处理的mc*目录"
    exit 1
fi

# 检查作业调度系统类型（SLURM or PBS）
if command -v sbatch >/dev/null 2>&1; then
    JOB_SYSTEM="SLURM"
    JOB_TEMPLATE="$SCRIPT_DIR/job_submit.sh"
    SUBMIT_CMD="sbatch"
elif command -v qsub >/dev/null 2>&1; then
    JOB_SYSTEM="PBS"
    JOB_TEMPLATE="$SCRIPT_DIR/pbs.sh"
    SUBMIT_CMD="qsub"
else
    echo "未检测到SLURM或PBS，使用本地模式"
    JOB_SYSTEM="LOCAL"
    JOB_TEMPLATE="$SCRIPT_DIR/local.sh"
    SUBMIT_CMD="bash $SCRIPT_DIR/job_submit_ht.sh"
fi

echo "使用调度系统: $JOB_SYSTEM"

# 日志输出配置（逐个 sbatch 提交）
LOG_ENABLE_RAW="$(printf '%s' "${RASPA_ENABLE_JOB_LOGS:-true}" | tr '[:upper:]' '[:lower:]')"
if [[ "$LOG_ENABLE_RAW" =~ ^(false|0|no)$ ]]; then LOG_ENABLE=false; else LOG_ENABLE=true; fi
LOG_SUBDIR=${RASPA_JOB_LOG_DIR:-1log}
if [[ "$LOG_SUBDIR" = /* ]]; then LOG_DIR="$LOG_SUBDIR"; else LOG_DIR="$WORK_DIR/$SUBDIR/$LOG_SUBDIR"; fi
if [ "$LOG_ENABLE" = true ]; then mkdir -p "$LOG_DIR"; fi

# 解析节点分配计划（若存在）
NODE_PLAN="${RASPA_NODE_PLAN:-}"
PLAN_MESSAGE=""
PLAN_FILE="$WORK_DIR/$SUBDIR/.raspa_node_plan"
if [ -z "$NODE_PLAN" ] && [ -f "$PLAN_FILE" ]; then
    NODE_PLAN="$(tr -d ' \t\r\n' < "$PLAN_FILE")"
fi
declare -a PLAN_QUEUE=()
PLAN_INDEX=0
if [ -n "$NODE_PLAN" ]; then
    IFS=',' read -ra PLAN_ENTRIES <<< "$NODE_PLAN"
    for entry in "${PLAN_ENTRIES[@]}"; do
        node="${entry%%:*}"
        count="${entry#*:}"
        if [ -n "$node" ] && [[ "$count" =~ ^[0-9]+$ ]] && [ "$count" -gt 0 ]; then
            for ((i=0; i<count; i++)); do
                PLAN_QUEUE+=("$node")
            done
        fi
    done
    if [ ${#PLAN_QUEUE[@]} -gt 0 ]; then
        PLAN_MESSAGE="节点分配计划: $NODE_PLAN"
    else
        NODE_PLAN=""
    fi
fi

# 选择提交模式（SLURM支持 job array 加速）
SUBMIT_MODE_RAW="${RASPA_SUBMIT_MODE:-auto}"
SUBMIT_MODE=$(printf '%s' "$SUBMIT_MODE_RAW" | tr '[:upper:]' '[:lower:]')
case "$SUBMIT_MODE" in
    array|loop|auto) ;;
    *) SUBMIT_MODE="auto";;
esac

if [ "$JOB_SYSTEM" != "SLURM" ]; then
    SUBMIT_MODE="loop"
elif [ "$SUBMIT_MODE" = "array" ] && [ -n "$NODE_PLAN" ]; then
    echo "⚠️  检测到节点分配计划，无法使用job array，自动降级为逐次提交模式。"
    SUBMIT_MODE="loop"
elif [ "$SUBMIT_MODE" = "auto" ]; then
    if [ -n "$NODE_PLAN" ]; then
        SUBMIT_MODE="loop"
    else
        SUBMIT_MODE="array"
    fi
fi

if [ "$SUBMIT_MODE" = "array" ]; then
    echo "提交模式: SLURM job array（批量提交，减少队列压测）"
else
    echo "提交模式: 逐次提交（兼容模式）"
fi

# 初始化并发上限文件（仅在不存在时写入，供 raspa-scale 动态调整）
LIMIT_FILE="$WORK_DIR/$SUBDIR/.raspa_worker_limit"
if [ ! -f "$LIMIT_FILE" ]; then
  echo "$CPU_CORES" > "$LIMIT_FILE"
fi

# 初始化指针队列（仅首次创建时进行一次快速扫描）
QDIR="$WORK_DIR/$SUBDIR/.raspa_queue"
Q_NEXT="$QDIR/next_id"
Q_LAST="$QDIR/last_id"
Q_RETRY="$QDIR/retry.list"
if [ ! -d "$QDIR" ]; then
  mkdir -p "$QDIR"
fi
if [ ! -f "$Q_NEXT" ] || [ ! -f "$Q_LAST" ]; then
  FIRST_ID=$(find "$WORK_DIR/$SUBDIR" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -printf '%f\n' 2>/dev/null | sed 's/^mc//' | sort -n | head -n1)
  LAST_ID=$(find "$WORK_DIR/$SUBDIR" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -printf '%f\n' 2>/dev/null | sed 's/^mc//' | sort -n | tail -n1)
  [ -z "$FIRST_ID" ] && FIRST_ID=1
  [ -z "$LAST_ID" ] && LAST_ID=0
  echo "$FIRST_ID" > "$Q_NEXT"
  echo "$LAST_ID" > "$Q_LAST"
fi
# 不清空重试队列，若不存在则创建
[ -f "$Q_RETRY" ] || : > "$Q_RETRY"

# 提交间隔控制，默认 0.05 秒，可通过 RASPA_SUBMIT_INTERVAL 调整（设为0即取消等待）
SUBMIT_INTERVAL_RAW="${RASPA_SUBMIT_INTERVAL:-0.01}"
case "$SUBMIT_INTERVAL_RAW" in
    ""|"0"|"0."|"0.0"|"0.00") SUBMIT_INTERVAL="0";;
    *) SUBMIT_INTERVAL="$SUBMIT_INTERVAL_RAW";;
esac

sleep_if_needed() {
    local delay="$1"
    case "$delay" in
        ""|"0"|"0."|"0.0"|"0.00") return 0;;
        *) sleep "$delay";;
    esac
}

# 否则走兼容模式：逐个提交（PBS/LOCAL 或 SUBMIT_MODE=LOOP）
# 支持从环境变量设置起始编号，便于“加号式”扩容（例如 RASPA_START_ID=201 CPU_CORES=300 提交 201..300）
START_ID=${RASPA_START_ID:-1}

if [ "$JOB_SYSTEM" = "SLURM" ] && [ "$SUBMIT_MODE" = "array" ]; then
    ARRAY_END=$((START_ID + CPU_CORES - 1))
    ARRAY_SCRIPT="$SCRIPT_DIR/job_sub_array.sh"
    rm -f "$ARRAY_SCRIPT"
    cp -rf "$JOB_TEMPLATE" "$ARRAY_SCRIPT"
    chmod 755 "$ARRAY_SCRIPT"
    # 确保 job array 模式下也使用正确的 runjobs 脚本
    mkdir -p "$WORK_DIR/job_templates"
    RASPA_VERSION_LOWER="$(echo "${RASPA_VERSION:-raspa2}" | tr '[:upper:]' '[:lower:]')"
    if [ "$RASPA_VERSION_LOWER" = "raspa3" ]; then
        if [ -f "$SCRIPT_DIR/runjobs_raspa3.sh" ]; then
            cp -f "$SCRIPT_DIR/runjobs_raspa3.sh" "$WORK_DIR/job_templates/runjobs.sh"
            echo "使用 RASPA3 执行脚本 (job array 模式)"
        else
            cp -f "$SCRIPT_DIR/runjobs.sh" "$WORK_DIR/job_templates/runjobs.sh"
        fi
    else
        cp -f "$SCRIPT_DIR/runjobs.sh" "$WORK_DIR/job_templates/runjobs.sh"
    fi
    chmod 755 "$WORK_DIR/job_templates/runjobs.sh"
    insert_exports_after_sbatch "$ARRAY_SCRIPT" \
        "export RASPA_TOTAL_CPUS=\"${CPU_CORES}\"" \
        "export RASPA_WORK_DIR=\"${topdir}\"" \
        "export RASPA_OUTPUT_DIR=\"${SUBDIR}\"" \
        "export RASPA_SUBDIR=\"${SUBDIR}\"" \
        "export RASPA_VERSION=\"${RASPA_VERSION:-raspa2}\""
    if [ "$LOG_ENABLE" = true ]; then
        sed -i -e "s|^#SBATCH --output=.*|#SBATCH --output=$LOG_DIR/%A_%a.out|" \
               -e "s|^#SBATCH --error=.*|#SBATCH --error=$LOG_DIR/%A_%a.err|" "$ARRAY_SCRIPT"
    else
        sed -i -e "s|^#SBATCH --output=.*|#SBATCH --output=/dev/null|" \
               -e "s|^#SBATCH --error=.*|#SBATCH --error=/dev/null|" "$ARRAY_SCRIPT"
    fi
    sed -i -e "s|^#SBATCH --job-name=.*|#SBATCH --job-name=raspa_array|" "$ARRAY_SCRIPT"
    echo "正在以 job array 提交 worker 范围 ${START_ID}-${ARRAY_END}..."
    submit_result=$($SUBMIT_CMD --array="${START_ID}-${ARRAY_END}" "$ARRAY_SCRIPT" 2>&1)
    echo "$submit_result"
    if [[ "$submit_result" =~ Submitted\ batch\ job\ ([0-9]+) ]]; then
        jobid="${BASH_REMATCH[1]}"
        echo "$jobid ${START_ID}-${ARRAY_END} $(date +%s) array" >> "$WORK_DIR/$SUBDIR/.raspa_jobs.list"
        echo "✅ Job array ${jobid} 提交完成（${START_ID}-${ARRAY_END}）"
    else
        echo "⚠️  未能解析 job array 的返回信息，请确认上方输出。"
    fi
    exit 0
fi

COUNTER=$START_ID
echo "开始逐个提交作业...（兼容模式）"
# 确保工作目录下拥有最新的 runjobs.sh（job_sub 会从 $RASPA_WORK_DIR/job_templates 读取）
mkdir -p "$WORK_DIR/job_templates"
# 根据 RASPA 版本选择正确的 runjobs 脚本
RASPA_VERSION_LOWER="$(echo "${RASPA_VERSION:-raspa2}" | tr '[:upper:]' '[:lower:]')"
if [ "$RASPA_VERSION_LOWER" = "raspa3" ]; then
    if [ -f "$SCRIPT_DIR/runjobs_raspa3.sh" ]; then
        cp -f "$SCRIPT_DIR/runjobs_raspa3.sh" "$WORK_DIR/job_templates/runjobs.sh"
        echo "使用 RASPA3 执行脚本"
    else
        echo "警告：找不到 runjobs_raspa3.sh，回退到 runjobs.sh"
        cp -f "$SCRIPT_DIR/runjobs.sh" "$WORK_DIR/job_templates/runjobs.sh"
    fi
else
    cp -f "$SCRIPT_DIR/runjobs.sh" "$WORK_DIR/job_templates/runjobs.sh"
    echo "使用 RASPA2 执行脚本"
fi
chmod 755 "$WORK_DIR/job_templates/runjobs.sh"
while [ $COUNTER -le $CPU_CORES ]
do
    NAMENEW=$COUNTER
    COUNTER=$((COUNTER + 1))
    cd "$WORK_DIR" || exit 1
    cp -rf "$JOB_TEMPLATE" "$SCRIPT_DIR/job_submit_ht.sh"
    insert_exports_after_sbatch "$SCRIPT_DIR/job_submit_ht.sh" \
        "export RASPA_TOTAL_CPUS=\"${CPU_CORES}\"" \
        "export RASPA_WORK_DIR=\"${topdir}\"" \
        "export RASPA_OUTPUT_DIR=\"${SUBDIR}\"" \
        "export RASPA_SUBDIR=\"${SUBDIR}\"" \
        "export RASPA_WORKER_ID=\"${NAMENEW}\"" \
        "export RASPA_VERSION=\"${RASPA_VERSION:-raspa2}\""
    sed -i -e "s|cd \$RASPA_WORK_DIR|cd $WORK_DIR|g" "$SCRIPT_DIR/job_submit_ht.sh"
    if [ "$JOB_SYSTEM" = "SLURM" ]; then
        sed -i -e "s|^#SBATCH --job-name=.*|#SBATCH --job-name=${NAMENEW}|" "$SCRIPT_DIR/job_submit_ht.sh"
        if [ -n "$NODE_PLAN" ] && [ ${#PLAN_QUEUE[@]} -gt 0 ] && [ $PLAN_INDEX -lt ${#PLAN_QUEUE[@]} ]; then
            TARGET_NODE="${PLAN_QUEUE[$PLAN_INDEX]}"
            PLAN_INDEX=$((PLAN_INDEX + 1))
            if [ -n "$TARGET_NODE" ]; then
                sed -i -e "s|^#SBATCH --nodelist=.*|#SBATCH --nodelist=${TARGET_NODE}|" \
                       -e "s|^# #SBATCH --nodelist=.*|#SBATCH --nodelist=${TARGET_NODE}|" "$SCRIPT_DIR/job_submit_ht.sh"
            fi
        fi
        if [ "$LOG_ENABLE" = true ]; then
            sed -i -e "s|^#SBATCH --output=.*|#SBATCH --output=$LOG_DIR/${NAMENEW}.out|" \
                   -e "s|^#SBATCH --error=.*|#SBATCH --error=$LOG_DIR/${NAMENEW}.err|" "$SCRIPT_DIR/job_submit_ht.sh"
        else
            sed -i -e "s|^#SBATCH --output=.*|#SBATCH --output=/dev/null|" \
                   -e "s|^#SBATCH --error=.*|#SBATCH --error=/dev/null|" "$SCRIPT_DIR/job_submit_ht.sh"
        fi
    elif [ "$JOB_SYSTEM" = "PBS" ]; then
        sed -i -e "s|#PBS -N .*|#PBS -N ${NAMENEW}|" "$SCRIPT_DIR/job_submit_ht.sh"
    fi
    if [ "$JOB_SYSTEM" = "SLURM" ] && [ -n "$TARGET_NODE" ]; then
        if grep -q "^#SBATCH --nodelist=" "$SCRIPT_DIR/job_submit_ht.sh"; then
            sed -i -e "s|^#SBATCH --nodelist=.*|#SBATCH --nodelist=${TARGET_NODE}|" "$SCRIPT_DIR/job_submit_ht.sh"
        elif grep -q "^# #SBATCH --nodelist=" "$SCRIPT_DIR/job_submit_ht.sh"; then
            sed -i -e "s|^# #SBATCH --nodelist=.*|#SBATCH --nodelist=${TARGET_NODE}|" "$SCRIPT_DIR/job_submit_ht.sh"
        else
            # 将指定节点插入到作业脚本的 #SBATCH 指令区域
            sed -i '3i #SBATCH --nodelist='"${TARGET_NODE}" "$SCRIPT_DIR/job_submit_ht.sh"
        fi
    fi
    echo "正在提交作业 $NAMENEW..."
    if [ "$JOB_SYSTEM" = "SLURM" ]; then
        if [ "$LOG_ENABLE" = true ]; then
            JOB_OUT="$LOG_DIR/${NAMENEW}.out"
            JOB_ERR="$LOG_DIR/${NAMENEW}.err"
        else
            JOB_OUT="/dev/null"
            JOB_ERR="/dev/null"
        fi
        submit_result=$($SUBMIT_CMD -o "$JOB_OUT" -e "$JOB_ERR" "$SCRIPT_DIR/job_submit_ht.sh" 2>&1)
    elif [ "$JOB_SYSTEM" = "PBS" ]; then
        if [ "$LOG_ENABLE" = true ]; then
            submit_result=$($SUBMIT_CMD -N "$NAMENEW" -o "$LOG_DIR/${NAMENEW}.out" -e "$LOG_DIR/${NAMENEW}.err" "$SCRIPT_DIR/job_submit_ht.sh" 2>&1)
        else
            submit_result=$($SUBMIT_CMD -N "$NAMENEW" "$SCRIPT_DIR/job_submit_ht.sh" 2>&1)
        fi
    else
        submit_result=$($SUBMIT_CMD 2>&1)
    fi
    echo "$submit_result"
    # 记录 JobId 与 worker 编号，便于后续缩放
    if [[ "$submit_result" =~ Submitted\ batch\ job\ ([0-9]+) ]]; then
        jobid="${BASH_REMATCH[1]}"
        echo "$jobid $NAMENEW $(date +%s)" >> "$WORK_DIR/$SUBDIR/.raspa_jobs.list"
    fi
    echo "✅ 作业 $NAMENEW 提交完成"
    if [ "$JOB_SYSTEM" = "LOCAL" ]; then
        sleep_if_needed "${RASPA_LOCAL_SUBMIT_INTERVAL:-1}"
    else
        sleep_if_needed "$SUBMIT_INTERVAL"
    fi
done

echo "🎉 所有作业已提交完成。请使用相应工具查看作业状态。"
if [ -n "$PLAN_MESSAGE" ]; then
    echo "$PLAN_MESSAGE"
fi
