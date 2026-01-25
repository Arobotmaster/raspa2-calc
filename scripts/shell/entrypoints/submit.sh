#!/bin/bash

set -euo pipefail

print_help() {
    echo "RASPA task submission"
    echo "Usage: submit.sh [cpu_cores]"
}

if [ $# -ge 1 ] && { [ "$1" = "-h" ] || [ "$1" = "--help" ]; }; then
    print_help
    exit 0
fi

# 获取当前工作目录（从环境变量）
if [ -n "${RASPA_WORK_DIR:-}" ]; then
    topdir="$(cd "$RASPA_WORK_DIR" && pwd -P)"
else
    topdir="$(pwd -P)"
fi
WORK_DIR="$topdir"

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "$SCRIPT_DIR/../lib" && pwd)"
TEMPLATE_DIR="$(cd "$SCRIPT_DIR/../templates/schedulers" && pwd)"

# 识别工具目录（优先环境变量，其次脚本路径，最后默认安装位置）
if [ -z "${RASPA_TOOL_DIR:-}" ]; then
    script_parent="$(cd "$SCRIPT_DIR/../../.." && pwd -P)"
    if [ -d "$script_parent/scripts/shell/entrypoints" ] && [ -d "$script_parent/src" ]; then
        RASPA_TOOL_DIR="$script_parent"
    elif [ -d "$HOME/raspa2-calc/.raspa_tools/scripts/shell/entrypoints" ]; then
        RASPA_TOOL_DIR="$HOME/raspa2-calc/.raspa_tools"
    fi
fi
export RASPA_TOOL_DIR

# 注：脚本在安装阶段已设置为可执行；避免在 NFS 上频繁 chmod 造成额外延迟

# 检查RASPA_DIR是否设置
if [ -z "${RASPA_DIR:-}" ]; then
    echo "错误：RASPA_DIR环境变量未设置"
    echo "请设置RASPA_DIR环境变量指向RASPA安装目录"
    exit 1
fi

# 获取CPU核心数参数，默认为2
CPU_CORES=${1:-2}
source "$LIB_DIR/disk.sh"

check_disk_space "$WORK_DIR"

echo "开始提交计算任务..."
echo "使用CPU核心数: $CPU_CORES"

# 智能检测子目录
detect_subdir() {
    # 优先使用环境/配置指定的子目录
    if [ -n "${RASPA_SUBDIR:-}" ] && [ -d "$topdir/$RASPA_SUBDIR" ]; then
        echo "$RASPA_SUBDIR"; return
    fi
    if [ -n "${RASPA_OUTPUT_DIR:-}" ] && [ -d "$topdir/$RASPA_OUTPUT_DIR" ]; then
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

prepare_job_submit_script() {
    local target="$1"
    shift
    cp -rf "$JOB_TEMPLATE" "$target"
    insert_exports_after_sbatch "$target" "$@"
}


SUBDIR=$(detect_subdir)
echo "检测到子目录: $SUBDIR"

# 任务清单检测（list-mode）
QDIR="$WORK_DIR/$SUBDIR/.raspa_queue"
TASK_LIST="$QDIR/tasks.list"
LIST_MODE=false
if [ -f "$TASK_LIST" ]; then
    LIST_MODE=true
fi

# 统计总任务数
if [ "$LIST_MODE" = true ]; then
    TOTAL_TASKS=$(awk 'END{print NR+0}' "$TASK_LIST" 2>/dev/null)
else
    TOTAL_TASKS=$(find "$topdir/$SUBDIR" -maxdepth 1 -type d -name "mc[0-9]*" ! -name "*__*" 2>/dev/null | wc -l)
fi
echo "检测到总任务数: $TOTAL_TASKS"

if [ "$TOTAL_TASKS" -eq 0 ]; then
    if [ "$LIST_MODE" = true ]; then
        echo "警告：未找到有效任务清单或清单为空"
    else
        echo "警告：未找到待处理的mc*目录"
    fi
    exit 1
fi

# 检查作业调度系统类型（SLURM or PBS）
if command -v sbatch >/dev/null 2>&1; then
    JOB_SYSTEM="SLURM"
    JOB_TEMPLATE="$TEMPLATE_DIR/job_submit.sh"
    SUBMIT_CMD="sbatch"
elif command -v qsub >/dev/null 2>&1; then
    JOB_SYSTEM="PBS"
    JOB_TEMPLATE="$TEMPLATE_DIR/pbs.sh"
    SUBMIT_CMD="qsub"
else
    echo "未检测到SLURM或PBS，使用本地模式"
    JOB_SYSTEM="LOCAL"
    JOB_TEMPLATE="$TEMPLATE_DIR/local.sh"
    SUBMIT_CMD="bash ${JOB_SUBMIT_HT:-}"
fi

echo "使用调度系统: $JOB_SYSTEM"

# SLURM 提交阶段加速：在本地临时目录缓存提交脚本，避免在 NFS(HDD) 上频繁读写临时脚本导致提交变慢
JOB_TEMPLATE_LOCAL="$JOB_TEMPLATE"
SUBMIT_TMP_DIR=""
JOB_SUBMIT_HT=""
ensure_submit_tmp_dir() {
    if [ -n "$SUBMIT_TMP_DIR" ] && [ -d "$SUBMIT_TMP_DIR" ]; then
        return 0
    fi
    local tmp_base
    tmp_base="${RASPA_SUBMIT_TMP_BASE:-${TMPDIR:-/tmp}}"
    SUBMIT_TMP_DIR=$(
      mktemp -d "${tmp_base%/}/raspa2calc_submit_${USER:-user}.XXXXXX" 2>/dev/null \
      || mktemp -d "/tmp/raspa2calc_submit_${USER:-user}.XXXXXX" 2>/dev/null \
      || true
    )
    if [ -z "$SUBMIT_TMP_DIR" ] || [ ! -d "$SUBMIT_TMP_DIR" ]; then
        SUBMIT_TMP_DIR="$WORK_DIR"
    else
        cleanup_submit_tmp() { rm -rf "$SUBMIT_TMP_DIR" 2>/dev/null || true; }
        trap cleanup_submit_tmp EXIT
    fi
    JOB_SUBMIT_HT="$SUBMIT_TMP_DIR/job_submit_ht.sh"
}
ensure_submit_tmp_dir
if [ "$JOB_SYSTEM" = "SLURM" ]; then
    if [ -n "$SUBMIT_TMP_DIR" ] && [ -d "$SUBMIT_TMP_DIR" ]; then
        JOB_TEMPLATE_LOCAL="$SUBMIT_TMP_DIR/job_submit.sh"
        cp -f "$JOB_TEMPLATE" "$JOB_TEMPLATE_LOCAL" 2>/dev/null || JOB_TEMPLATE_LOCAL="$JOB_TEMPLATE"
        chmod 755 "$JOB_TEMPLATE_LOCAL" 2>/dev/null || true
    fi
fi

if [ "$JOB_SYSTEM" = "LOCAL" ]; then
    SUBMIT_CMD="bash $JOB_SUBMIT_HT"
fi

# 日志输出配置（逐个 sbatch 提交）
LOG_ENABLE_RAW="$(printf '%s' "${RASPA_ENABLE_JOB_LOGS:-true}" | tr '[:upper:]' '[:lower:]')"
if [[ "$LOG_ENABLE_RAW" =~ ^(false|0|no)$ ]]; then LOG_ENABLE=false; else LOG_ENABLE=true; fi
LOG_SUBDIR=${RASPA_JOB_LOG_DIR:-1log}
if [[ "$LOG_SUBDIR" = /* ]]; then LOG_DIR="$LOG_SUBDIR"; else LOG_DIR="$WORK_DIR/$SUBDIR/$LOG_SUBDIR"; fi
if [ "$LOG_ENABLE" = true ]; then mkdir -p "$LOG_DIR"; fi

# 解析节点分配计划（若存在）
# 注意：本集群 SLURM 为 SelectTypeParameters=CR_CORE（按“物理核”作为可消耗资源），
# 在超线程节点上单个 sbatch 作业会占用 1 个 core = 2 个 CPU(thread)。
# 为了让 RASPA 单线程任务用满这些 thread，需要在同一个作业内启动多个 worker。

SCHED_CR_CORE=false
if [ "$JOB_SYSTEM" = "SLURM" ] && command -v scontrol >/dev/null 2>&1; then
    sel=$(scontrol show config 2>/dev/null | awk -F= '/SelectTypeParameters/ {gsub(/ /,"",$2); print $2; exit}' || echo "")
    case "${sel^^}" in *CR_CORE*) SCHED_CR_CORE=true ;; esac
fi

# 探测每个节点的 ThreadsPerCore（来自 sinfo 拓扑 %z = S:C:T）
declare -A NODE_TPC=()
if [ "$JOB_SYSTEM" = "SLURM" ] && command -v sinfo >/dev/null 2>&1; then
    while IFS='|' read -r nm topo; do
        [ -z "$nm" ] && continue
        tpc=1
        if [[ "$topo" =~ ^[0-9]+:[0-9]+:[0-9]+$ ]]; then
            tpc="${topo##*:}"
            [[ "$tpc" =~ ^[0-9]+$ ]] || tpc=1
        fi
        NODE_TPC["$nm"]=$tpc
    done < <(sinfo -N -h -o '%N|%z' 2>/dev/null)
fi

clean_plan() { printf "%s" "$1" | tr -d ' \t\r\n\"' ; }

NODE_PLAN="$(clean_plan "${RASPA_NODE_PLAN:-}")"
PLAN_FILE="$WORK_DIR/$SUBDIR/.raspa_node_plan"
if [ -z "$NODE_PLAN" ] && [ -f "$PLAN_FILE" ]; then
    NODE_PLAN="$(clean_plan "$(cat "$PLAN_FILE")")"
fi

PLAN_MESSAGE=""
declare -a PLAN_QUEUE=()
declare -A NODE_REMAIN=()
PLAN_INDEX=0

if [ -n "$NODE_PLAN" ]; then
    IFS=',' read -ra PLAN_ENTRIES <<< "$NODE_PLAN"
    for entry in "${PLAN_ENTRIES[@]}"; do
        node="${entry%%:*}"
        count="${entry#*:}"
        if [ -z "$node" ] || ! [[ "$count" =~ ^[0-9]+$ ]] || [ "$count" -le 0 ]; then
            continue
        fi
        NODE_REMAIN["$node"]=$(( ${NODE_REMAIN["$node"]:-0} + count ))

        tpc="${NODE_TPC["$node"]:-1}"
        jobs="$count"
        if [ "$SCHED_CR_CORE" = true ] && [ "$tpc" -gt 1 ]; then
            jobs=$(( (count + tpc - 1) / tpc ))
        fi
        for ((i=0; i<jobs; i++)); do
            PLAN_QUEUE+=("$node")
        done
    done

    if [ ${#PLAN_QUEUE[@]} -gt 0 ]; then
        if [ "$SCHED_CR_CORE" = true ]; then
            declare -A JOB_COUNTS=()
            for n in "${PLAN_QUEUE[@]}"; do
                JOB_COUNTS["$n"]=$(( ${JOB_COUNTS["$n"]:-0} + 1 ))
            done
            JOB_PLAN=""
            for n in "${!JOB_COUNTS[@]}"; do
                JOB_PLAN+="${n}:${JOB_COUNTS[$n]},"
            done
            JOB_PLAN="${JOB_PLAN%,}"
            PLAN_MESSAGE="节点分配计划(线程->作业): ${NODE_PLAN} -> ${JOB_PLAN}"
        else
            PLAN_MESSAGE="节点分配计划: ${NODE_PLAN}"
        fi
    else
        NODE_PLAN=""
    fi
fi

# 若有节点计划，结合当前 sinfo 动态裁剪不可用节点/超额数量，避免卡在 ReqNodeNotAvail
if [ -n "$NODE_PLAN" ] && [ "$JOB_SYSTEM" = "SLURM" ] && command -v sinfo >/dev/null 2>&1; then
    declare -A NODE_FREE_JOBS=()
    while IFS='|' read -r nm cc; do
        [ -z "$nm" ] && continue
        IFS='/' read -r alloc idle other total <<< "$cc"
        alloc=${alloc:-0}; other=${other:-0}; total=${total:-0}
        free_threads=$(( total - alloc - other ))
        [ "$free_threads" -lt 0 ] && free_threads=0
        tpc="${NODE_TPC["$nm"]:-1}"
        free_jobs=$free_threads
        if [ "$SCHED_CR_CORE" = true ] && [ "$tpc" -gt 1 ]; then
            free_jobs=$(( free_threads / tpc ))
        fi
        NODE_FREE_JOBS["$nm"]=$free_jobs
    done < <(sinfo -N -h -o '%N|%C' 2>/dev/null)

    if [ ${#NODE_FREE_JOBS[@]} -gt 0 ]; then
        filtered=()
        for n in "${PLAN_QUEUE[@]}"; do
            free=${NODE_FREE_JOBS["$n"]:-0}
            if [ "$free" -le 0 ]; then
                continue
            fi
            filtered+=("$n")
            NODE_FREE_JOBS["$n"]=$(( free - 1 ))
        done
        PLAN_QUEUE=("${filtered[@]}")
        if [ ${#PLAN_QUEUE[@]} -eq 0 ]; then
            echo "⚠️  当前节点分配计划的节点均无空闲 core，已清空节点计划以避免 PD。"
            NODE_PLAN=""
            PLAN_MESSAGE=""
        else
            if [ "$SCHED_CR_CORE" = true ]; then
                declare -A JOB_COUNTS=()
                for n in "${PLAN_QUEUE[@]}"; do
                    JOB_COUNTS["$n"]=$(( ${JOB_COUNTS["$n"]:-0} + 1 ))
                done
                JOB_PLAN=""
                for n in "${!JOB_COUNTS[@]}"; do
                    JOB_PLAN+="${n}:${JOB_COUNTS[$n]},"
                done
                JOB_PLAN="${JOB_PLAN%,}"
                PLAN_MESSAGE="节点分配计划(按空闲裁剪, 线程->作业): ${NODE_PLAN} -> ${JOB_PLAN}"
            else
                PLAN_MESSAGE="节点分配计划(按空闲裁剪): ${NODE_PLAN}"
            fi
        fi
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

# DEBUG
echo "DEBUG: 准备初始化并发上限文件..."

# 初始化并发上限文件（仅在不存在时写入，供 raspa-scale 动态调整）
LIMIT_FILE="$WORK_DIR/$SUBDIR/.raspa_worker_limit"
if [ ! -f "$LIMIT_FILE" ]; then
  echo "$CPU_CORES" > "$LIMIT_FILE"
else
  cur_lim=$(awk 'NR==1&&$1~/^[0-9]+$/{print $1; exit}' "$LIMIT_FILE" 2>/dev/null || echo "")
  if [ -n "$cur_lim" ] && [ "$cur_lim" -lt "$CPU_CORES" ] 2>/dev/null; then
    echo "$CPU_CORES" > "$LIMIT_FILE"
    echo "提示：检测到旧的并发上限($cur_lim) < 本次提交($CPU_CORES)，已自动更新为 $CPU_CORES"
  fi
fi

echo "DEBUG: 准备初始化指针队列..."

# 初始化指针队列（仅首次创建时进行一次快速扫描）
Q_NEXT="$QDIR/next_id"
Q_LAST="$QDIR/last_id"
Q_RETRY="$QDIR/retry.list"
if [ ! -d "$QDIR" ]; then
  mkdir -p "$QDIR"
fi
if [ ! -f "$Q_NEXT" ] || [ ! -f "$Q_LAST" ]; then
  if [ "$LIST_MODE" = true ] && [ -f "$TASK_LIST" ]; then
    TASK_TOTAL=$(awk 'END{print NR+0}' "$TASK_LIST" 2>/dev/null)
    [ -z "$TASK_TOTAL" ] && TASK_TOTAL=0
    echo 1 > "$Q_NEXT"
    echo "$TASK_TOTAL" > "$Q_LAST"
  else
    echo "DEBUG: 扫描 mc* 目录以确定任务范围..."
    FIRST_ID=$(find "$WORK_DIR/$SUBDIR" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -printf '%f\n' 2>/dev/null | sed 's/^mc//' | sort -n | head -n1 || echo "")
    LAST_ID=$(find "$WORK_DIR/$SUBDIR" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -printf '%f\n' 2>/dev/null | sed 's/^mc//' | sort -n | tail -n1 || echo "")
    [ -z "$FIRST_ID" ] && FIRST_ID=1
    [ -z "$LAST_ID" ] && LAST_ID=0
    echo "$FIRST_ID" > "$Q_NEXT"
    echo "$LAST_ID" > "$Q_LAST"
  fi
fi
# 不清空重试队列，若不存在则创建
[ -f "$Q_RETRY" ] || : > "$Q_RETRY"

echo "DEBUG: 准备进入提交循环..."

# 提交间隔控制，默认 0.1 秒，可通过 RASPA_SUBMIT_INTERVAL 调整（设为0即取消等待）
SUBMIT_INTERVAL_RAW="${RASPA_SUBMIT_INTERVAL:-0.1}"
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
    echo "正在以 job array 提交 worker 范围 ${START_ID}-${ARRAY_END}..."
    if [ "$LOG_ENABLE" = true ]; then
        JOB_OUT="$LOG_DIR/%A_%a.out"
        JOB_ERR="$LOG_DIR/%A_%a.err"
    else
        JOB_OUT="/dev/null"
        JOB_ERR="/dev/null"
    fi
    EXPORTS="ALL,RASPA_TOTAL_CPUS=${CPU_CORES},RASPA_WORK_DIR=${topdir},RASPA_OUTPUT_DIR=${SUBDIR},RASPA_SUBDIR=${SUBDIR},RASPA_VERSION=${RASPA_VERSION:-raspa2},RASPA_TOOL_DIR=${RASPA_TOOL_DIR:-}"
    submit_result=$($SUBMIT_CMD --array="${START_ID}-${ARRAY_END}" --job-name="raspa_array" -o "$JOB_OUT" -e "$JOB_ERR" --export="$EXPORTS" "$JOB_TEMPLATE_LOCAL" 2>&1)
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
while [ $COUNTER -le $CPU_CORES ]
do
    TARGET_NODE=""
    WORKERS_PER_JOB=1

    # 若指定了节点计划，则按计划选择目标节点；在 CR_CORE 的超线程节点上，每个作业会占用 1 core(=T 个 thread)
    if [ "$JOB_SYSTEM" = "SLURM" ] && [ -n "$NODE_PLAN" ] && [ ${#PLAN_QUEUE[@]} -gt 0 ] && [ $PLAN_INDEX -lt ${#PLAN_QUEUE[@]} ]; then
        TARGET_NODE="${PLAN_QUEUE[$PLAN_INDEX]}"
        PLAN_INDEX=$((PLAN_INDEX + 1))
        if [ "$SCHED_CR_CORE" = true ]; then
            tpc="${NODE_TPC["$TARGET_NODE"]:-1}"
            if [ -n "$tpc" ] && [ "$tpc" -gt 1 ] 2>/dev/null; then
                WORKERS_PER_JOB="$tpc"
                rem="${NODE_REMAIN["$TARGET_NODE"]:-0}"
                if [ -n "$rem" ] && [ "$rem" -gt 0 ] 2>/dev/null; then
                    if [ "$rem" -lt "$WORKERS_PER_JOB" ] 2>/dev/null; then
                        WORKERS_PER_JOB="$rem"
                    fi
                    NODE_REMAIN["$TARGET_NODE"]=$(( rem - WORKERS_PER_JOB ))
                fi
            fi
        fi
    fi

    # 为本次作业分配一个或多个 worker 编号（用于 runjobs.sh 的 CPU 参数与 .workers 文件名）
    WORKER_IDS=()
    for ((i=0; i<WORKERS_PER_JOB; i++)); do
        wid=$((COUNTER + i))
        if [ "$wid" -le "$CPU_CORES" ]; then
            WORKER_IDS+=("$wid")
        fi
    done
    if [ ${#WORKER_IDS[@]} -eq 0 ]; then
        break
    fi
    NAMENEW="${WORKER_IDS[0]}"
    WORKER_IDS_CSV=$(IFS=,; echo "${WORKER_IDS[*]}")
    WORKER_COUNT="${#WORKER_IDS[@]}"
    COUNTER=$((COUNTER + WORKER_COUNT))

    last_wid="${WORKER_IDS[$(( WORKER_COUNT - 1 ))]}"
    echo "正在提交第${last_wid}个任务…"
    EXPORT_LINES=(
        "export RASPA_TOTAL_CPUS=\"${CPU_CORES}\""
        "export RASPA_WORK_DIR=\"${topdir}\""
        "export RASPA_OUTPUT_DIR=\"${SUBDIR}\""
        "export RASPA_SUBDIR=\"${SUBDIR}\""
        "export RASPA_WORKER_ID=\"${NAMENEW}\""
        "export RASPA_WORKER_IDS=\"${WORKER_IDS_CSV}\""
        "export RASPA_VERSION=\"${RASPA_VERSION:-raspa2}\""
        "export RASPA_TOOL_DIR=\"${RASPA_TOOL_DIR:-}\""
    )
    if [ "$JOB_SYSTEM" = "SLURM" ]; then
        if [ "$LOG_ENABLE" = true ]; then
            JOB_OUT="$LOG_DIR/${NAMENEW}.out"
            JOB_ERR="$LOG_DIR/${NAMENEW}.err"
        else
            JOB_OUT="/dev/null"
            JOB_ERR="/dev/null"
        fi
        EXPORTS="ALL,RASPA_TOTAL_CPUS=${CPU_CORES},RASPA_WORK_DIR=${topdir},RASPA_OUTPUT_DIR=${SUBDIR},RASPA_SUBDIR=${SUBDIR},RASPA_WORKER_ID_START=${NAMENEW},RASPA_WORKER_COUNT=${WORKER_COUNT},RASPA_VERSION=${RASPA_VERSION:-raspa2},RASPA_TOOL_DIR=${RASPA_TOOL_DIR:-}"
        if [ -n "$TARGET_NODE" ]; then
            submit_result=$($SUBMIT_CMD --nodelist="$TARGET_NODE" --job-name="$NAMENEW" -o "$JOB_OUT" -e "$JOB_ERR" --export="$EXPORTS" "$JOB_TEMPLATE_LOCAL" 2>&1)
        else
            submit_result=$($SUBMIT_CMD --job-name="$NAMENEW" -o "$JOB_OUT" -e "$JOB_ERR" --export="$EXPORTS" "$JOB_TEMPLATE_LOCAL" 2>&1)
        fi
    elif [ "$JOB_SYSTEM" = "PBS" ]; then
        cd "$WORK_DIR" || exit 1
        prepare_job_submit_script "$JOB_SUBMIT_HT" "${EXPORT_LINES[@]}"
        sed -i -e "s|#PBS -N .*|#PBS -N ${NAMENEW}|" "$JOB_SUBMIT_HT"
        if [ "$LOG_ENABLE" = true ]; then
            submit_result=$($SUBMIT_CMD -N "$NAMENEW" -o "$LOG_DIR/${NAMENEW}.out" -e "$LOG_DIR/${NAMENEW}.err" "$JOB_SUBMIT_HT" 2>&1)
        else
            submit_result=$($SUBMIT_CMD -N "$NAMENEW" "$JOB_SUBMIT_HT" 2>&1)
        fi
    else
        cd "$WORK_DIR" || exit 1
        prepare_job_submit_script "$JOB_SUBMIT_HT" "${EXPORT_LINES[@]}"
        submit_result=$($SUBMIT_CMD 2>&1)
    fi
    echo "$submit_result"
    # 记录 JobId 与 worker 编号，便于后续缩放
    if [[ "$submit_result" =~ Submitted\ batch\ job\ ([0-9]+) ]]; then
        jobid="${BASH_REMATCH[1]}"
        echo "$jobid $NAMENEW $(date +%s) $WORKER_IDS_CSV" >> "$WORK_DIR/$SUBDIR/.raspa_jobs.list"
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
