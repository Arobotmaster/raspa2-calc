#!/bin/bash
#
# RASPA3 高通量计算执行脚本
# 基于 runjobs.sh 修改，支持 RASPA3 的 JSON 格式输入
#

# 优先加载任务目录下的配置快照，补交作业继承原始配置
CWD="$(pwd -P)"
eval "$(
  python3 - <<'PY'
import os, sys, json

candidates = [
    os.path.join(os.getcwd(), ".raspa_config.yaml"),
    os.path.join(os.getcwd(), "config.yaml"),
    os.path.expanduser("~/raspa2-calc/.raspa_tools/config.yaml"),
]
cfg_path = next((p for p in candidates if os.path.exists(p)), None)
if not cfg_path:
    sys.exit(0)

def load_cfg(path: str):
    try:
        import yaml  # type: ignore
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

cfg = load_cfg(cfg_path)

def emit(key, val):
    if val in (None, ""):
        return
    if os.environ.get(key):
        return
    print(f'export {key}="{val}"')

env = cfg.get("environment") or {}
calc = cfg.get("calculation") or {}

emit("RASPA3_CONDA_ENV", env.get("raspa3_conda_env"))
emit("RASPA3_JSON_DIR", env.get("raspa3_json_dir"))
emit("RASPA3_CIF_BASE_PATH", env.get("raspa3_cif_base_path"))
emit("RASPA3_TEMPLATE_PATH", env.get("raspa3_template_path"))

mser = calc.get("mser") if isinstance(calc, dict) else {}
if isinstance(mser, dict):
    emit("RASPA_MSER_ENABLE", str(mser.get("enable", False)).lower())
    emit("RASPA_MSER_TARGET_CYCLES", mser.get("target_cycles"))
    emit("RASPA_MSER_ADD_CYCLES", mser.get("add_cycles"))
    emit("RASPA_MSER_MAX_ITER", mser.get("max_iter"))
    emit("RASPA_MSER_UNCERTAINTY", mser.get("uncertainty"))
    emit("RASPA_MSER_CONDA_ENV", mser.get("conda_env"))
    emit("RASPA_MSER_LLM", str(mser.get("llm", True)).lower())
    emit("RASPA_MSER_BATCH_SIZE", mser.get("batch_size"))
PY
)"

# ============ RASPA3 环境设置 ============
# 初始化 conda
if [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
fi

# 激活 raspa3 conda 环境
RASPA3_CONDA_ENV="${RASPA3_CONDA_ENV:-raspa3}"
conda activate "$RASPA3_CONDA_ENV" 2>/dev/null || {
    echo "警告：无法激活 conda 环境 $RASPA3_CONDA_ENV，尝试使用系统 raspa3"
}

# 检查 raspa3 命令
if ! command -v raspa3 &> /dev/null; then
    echo "错误：找不到 raspa3 命令"
    echo "请确保已安装 RASPA3 并激活正确的 conda 环境"
    exit 1
fi

MSER_MODULE="raspa_calc.algorithms.auto_mser_raspa3"
MSER_PYTHONPATH="${RASPA_TOOL_DIR:-$HOME/raspa2-calc/.raspa_tools}/scripts/python"
export PYTHONPATH="${MSER_PYTHONPATH}${PYTHONPATH:+:$PYTHONPATH}"

# ============ 目录检测 ============
detect_subdir() {
    if [ -n "$RASPA_SUBDIR" ] && [ -d "$CWD/$RASPA_SUBDIR" ]; then
        echo "$RASPA_SUBDIR"; return
    fi
    if [ -n "$RASPA_OUTPUT_DIR" ] && [ -d "$CWD/$RASPA_OUTPUT_DIR" ]; then
        echo "$RASPA_OUTPUT_DIR"; return
    fi
    local found_subdirs
    found_subdirs=$(find "$CWD" -maxdepth 2 -type d -name "mc[0-9]*" ! -name "*__*" 2>/dev/null | head -1)
    if [ -n "$found_subdirs" ]; then
        local d
        d="$(dirname "$found_subdirs")"
        if [ "$d" = "$CWD" ]; then
            echo "."
        else
            d="${d#$CWD/}"
            echo "$d"
        fi
    else
        echo "."
    fi
}

# 使用当前真实工作目录
CWD="$(pwd -P)"
topdir="$CWD"
subdir=$(detect_subdir)
CPU=${1:-1}
TOTAL_CPUS=${2:-1}

# ============ 并发控制 ============
LIMIT_FILE="${topdir}/${subdir}/.raspa_worker_limit"
read_limit() {
    if [ -f "$LIMIT_FILE" ]; then
        awk 'NR==1&&$1~/^[0-9]+$/{print $1; exit}' "$LIMIT_FILE"
    fi
}

SHOULD_EXIT_NOW() {
    local lim
    lim=$(read_limit)
    [ -z "$lim" ] && lim=$TOTAL_CPUS
    if [ "$CPU" -gt "$lim" ]; then
        return 0
    fi
    return 1
}

# ============ 任务队列 ============
thiscore=$$
LOGFILE=${topdir}/log__${subdir}_raspa3_output
WORKERS_DIR="${topdir}/${subdir}/.workers"
mkdir -p "$WORKERS_DIR"

if [ -n "$RASPA_WORKER_ID" ]; then
    WORKER_ID="$RASPA_WORKER_ID"
elif [ -n "$SLURM_ARRAY_JOB_ID" ] && [ -n "$SLURM_ARRAY_TASK_ID" ]; then
    WORKER_ID="${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
elif [ -n "$SLURM_ARRAY_TASK_ID" ]; then
    WORKER_ID="${SLURM_ARRAY_TASK_ID}"
elif [ -n "$SLURM_JOB_ID" ]; then
    WORKER_ID="$SLURM_JOB_ID"
else
    WORKER_ID="local-$$"
fi

QDIR="${topdir}/${subdir}/.raspa_queue"
Q_NEXT="$QDIR/next_id"
Q_LAST="$QDIR/last_id"
Q_RETRY="$QDIR/retry.list"
Q_LOCK="$QDIR/next.lock"
TASK_LIST="$QDIR/tasks.list"
LIST_MODE=0
if [ -f "$TASK_LIST" ]; then
    LIST_MODE=1
fi
CLAIMED_TASK_DIR=""
CLAIMED_TASK_ID=""
CLAIMED_TASK_REL=""
mkdir -p "$QDIR"
LOCK_STALE_SECONDS="${RASPA_LOCK_STALE_SECONDS:-30}"
QUEUE_RESCAN_INTERVAL_SECONDS="${RASPA_QUEUE_RESCAN_INTERVAL_SECONDS:-5}"
LAST_RESCAN_EPOCH=0
CURRENT_LOCK_FILE=""

is_lock_stale() {
    local f="$1"
    [ -f "$f" ] || return 1
    local now mtime age
    now=$(date +%s)
    mtime=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    [[ "$mtime" =~ ^[0-9]+$ ]] || mtime=0
    age=$((now - mtime))
    [ "$age" -ge "$LOCK_STALE_SECONDS" ]
}

cleanup_lock_if_stale() {
    local f="$1"
    if is_lock_stale "$f"; then
        rm -f "$f" 2>/dev/null || true
    fi
}

get_task_rel() {
    local id="$1"
    [ -z "$id" ] && return 1
    sed -n "${id}p" "$TASK_LIST" 2>/dev/null | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

task_base_dir() {
    local id="$1"
    if [ "$LIST_MODE" -eq 1 ]; then
        local rel
        rel="$(get_task_rel "$id")"
        [ -z "$rel" ] && return 1
        rel="${rel%/}"
        echo "$topdir/$subdir/$rel"
    else
        echo "$topdir/$subdir/mc${id}"
    fi
}

ensure_queue() {
    if [ ! -f "$Q_NEXT" ] || [ ! -f "$Q_LAST" ]; then
        if [ "$LIST_MODE" -eq 1 ] && [ -f "$TASK_LIST" ]; then
            local total
            total=$(awk 'END{print NR+0}' "$TASK_LIST" 2>/dev/null)
            [ -z "$total" ] && total=0
            echo 1 > "$Q_NEXT"
            echo "$total" > "$Q_LAST"
        else
            local ids
            mapfile -t ids < <(find "$topdir/$subdir" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -printf '%f\n' 2>/dev/null | sed 's/^mc//' | sort -n)
            if [ ${#ids[@]} -eq 0 ]; then
                echo 1 > "$Q_NEXT"
                echo 0 > "$Q_LAST"
            else
                echo "${ids[0]}" > "$Q_NEXT"
                echo "${ids[-1]}" > "$Q_LAST"
            fi
        fi
    fi
    [ -f "$Q_RETRY" ] || : > "$Q_RETRY"
}

claim_from_retry() {
    local tmp="$Q_RETRY.$WORKER_ID.tmp"
    if [ ! -s "$Q_RETRY" ]; then return 1; fi

    mv "$Q_RETRY" "$tmp" 2>/dev/null || return 1
    local claimed=""
    local -a pending_ids=()
    while IFS= read -r id; do
        [ -z "$id" ] && continue
        local workdir
        workdir="$(task_base_dir "$id")" || continue
        local task_rel=""
        if [ "$LIST_MODE" -eq 1 ]; then
            task_rel="$(get_task_rel "$id")"
            [ -z "$task_rel" ] && continue
        fi
        # 已完成的任务不再写回重试队列
        if [ -d "${workdir}__done" ] || [ -d "${workdir}__failed" ] || [ -d "${workdir}__running" ]; then
            continue
        fi
        if [ -d "$workdir" ]; then
            local lock_file="${workdir}.lock"
            cleanup_lock_if_stale "$lock_file"
            if (set -o noclobber; echo "$$" > "$lock_file") 2>/dev/null; then
                CURRENT_LOCK_FILE="$lock_file"
                # RASPA3: 检查 simulation.json
                if [ -f "${workdir}/simulation.json" ]; then
                    if mv "$workdir" "${workdir}__running"; then
                        rm -f "$lock_file"
                        CURRENT_LOCK_FILE=""
                        CLAIMED_TASK_DIR="${workdir}__running"
                        CLAIMED_TASK_ID="$id"
                        CLAIMED_TASK_REL="$task_rel"
                        claimed="yes"
                        # 将剩余未处理的 pending_ids 写回
                        for pid in "${pending_ids[@]}"; do
                            echo "$pid" >> "$Q_RETRY"
                        done
                        break
                    else
                        rm -f "$lock_file"
                        CURRENT_LOCK_FILE=""
                    fi
                else
                    rm -f "$lock_file"
                    CURRENT_LOCK_FILE=""
                fi
            fi
            # 无法锁定时加入待重试列表（去重）
            local dup=0
            for pid in "${pending_ids[@]}"; do
                [ "$pid" = "$id" ] && { dup=1; break; }
            done
            [ "$dup" -eq 0 ] && pending_ids+=("$id")
        fi
    done < "$tmp"
    rm -f "$tmp"
    # 如果没有成功认领，将待重试列表写回
    if [ -z "$claimed" ]; then
        for pid in "${pending_ids[@]}"; do
            echo "$pid" >> "$Q_RETRY"
        done
    fi
    [ -n "$claimed" ] && return 0 || return 1
}

claim_from_pointer() {
    local id=""
    while :; do
        [ -d "$QDIR" ] || mkdir -p "$QDIR"
        exec 9>"$Q_LOCK" 2>/dev/null || { sleep 0.05; continue; }
        if flock -n 9; then
            local curr=$(awk 'NR==1{print $1; exit}' "$Q_NEXT" 2>/dev/null)
            local last=$(awk 'NR==1{print $1; exit}' "$Q_LAST" 2>/dev/null)
            [ -z "$curr" ] && curr=1
            [ -z "$last" ] && last=0
            if [ "$curr" -gt "$last" ]; then
                flock -u 9
                exec 9>&-
                return 1
            fi
            echo $((curr + 1)) > "$Q_NEXT"
            flock -u 9
            exec 9>&-
            id="$curr"
        else
            exec 9>&-
            sleep 0.05
            continue
        fi

        local workdir
        workdir="$(task_base_dir "$id")" || continue
        local task_rel=""
        if [ "$LIST_MODE" -eq 1 ]; then
            task_rel="$(get_task_rel "$id")"
            [ -z "$task_rel" ] && continue
        fi
        if [ ! -d "$workdir" ]; then
            continue
        fi
        if [ -d "${workdir}__done" ] || [ -d "${workdir}__failed" ] || [ -d "${workdir}__running" ]; then
            continue
        fi
        local lock_file="${workdir}.lock"
        cleanup_lock_if_stale "$lock_file"
        if (set -o noclobber; echo "$$" > "$lock_file") 2>/dev/null; then
            CURRENT_LOCK_FILE="$lock_file"
            # RASPA3: 检查 simulation.json
            if [ -f "${workdir}/simulation.json" ]; then
                if mv "$workdir" "${workdir}__running"; then
                    rm -f "$lock_file"
                    CURRENT_LOCK_FILE=""
                    CLAIMED_TASK_DIR="${workdir}__running"
                    CLAIMED_TASK_ID="$id"
                    CLAIMED_TASK_REL="$task_rel"
                    return 0
                else
                    rm -f "$lock_file"
                    CURRENT_LOCK_FILE=""
                fi
            else
                rm -f "$lock_file"
                CURRENT_LOCK_FILE=""
            fi
        fi
    done
}

rescan_pending() {
    if [ "$LIST_MODE" -eq 1 ]; then
        [ -f "$TASK_LIST" ] || return 1
        local existing_ids=()
        if [ -f "$Q_RETRY" ] && [ -s "$Q_RETRY" ]; then
            mapfile -t existing_ids < "$Q_RETRY"
        fi
        exec 8>>"$Q_RETRY"
        if ! flock -n 8; then
            exec 8>&-
            return 1
        fi
        local added=0
        local line_id=0
        while IFS= read -r rel || [ -n "$rel" ]; do
            line_id=$((line_id + 1))
            rel="$(printf '%s' "$rel" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
            [ -z "$rel" ] && continue
            local base="$topdir/$subdir/${rel%/}"
            if [ -d "$base" ] && [ ! -d "${base}__running" ] && [ ! -d "${base}__done" ] && [ ! -d "${base}__failed" ]; then
                local duplicate=0
                for eid in "${existing_ids[@]}"; do
                    if [ "$eid" = "$line_id" ]; then
                        duplicate=1
                        break
                    fi
                done
                if [ "$duplicate" -eq 1 ]; then
                    continue
                fi
                echo "$line_id" >&8
                existing_ids+=("$line_id")
                added=1
            fi
        done < "$TASK_LIST"
        flock -u 8
        exec 8>&-
        [ "$added" -gt 0 ]
        return
    fi
    local pending_dirs=()
    mapfile -t pending_dirs < <(find "$topdir/$subdir" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -printf '%f\n' 2>/dev/null | sort -n)
    if [ ${#pending_dirs[@]} -eq 0 ]; then
        return 1
    fi

    local existing_ids=()
    if [ -f "$Q_RETRY" ] && [ -s "$Q_RETRY" ]; then
        mapfile -t existing_ids < "$Q_RETRY"
    fi

    exec 8>>"$Q_RETRY"
    if ! flock -n 8; then
        exec 8>&-
        return 1
    fi

    local added=0
    for name in "${pending_dirs[@]}"; do
        local id="${name#mc}"
        [[ "$id" =~ ^[0-9]+$ ]] || continue
        local duplicate=0
        for eid in "${existing_ids[@]}"; do
            if [ "$eid" = "$id" ]; then
                duplicate=1
                break
            fi
        done
        if [ "$duplicate" -eq 1 ]; then
            continue
        fi
        echo "$id" >&8
        existing_ids+=("$id")
        added=1
    done

    flock -u 8
    exec 8>&-

    [ "$added" -gt 0 ]
}

# ============ 任务状态管理 ============
CURRENT_TASK_DIR=""
mark_start() {
    local dir="$1"; local idx="$2"; local epoch
    epoch=$(date +%s)
    CURRENT_TASK_DIR="$dir"
    {
        echo "jobid=$WORKER_ID"
        echo "mc=$idx"
        [ -n "$CLAIMED_TASK_REL" ] && echo "task=$CLAIMED_TASK_REL"
        echo "start=$epoch"
        echo "host=$(hostname)"
        echo "cpu=$CPU"
    } > "$WORKERS_DIR/$WORKER_ID"
    {
        echo "jobid=$WORKER_ID"
        echo "cpu=$CPU"
        echo "start=$epoch"
    } > "$dir/.worker_info"
}

mark_clear() {
    rm -f "$WORKERS_DIR/$WORKER_ID" 2>/dev/null || true
}

cleanup_trap() {
    pkill -TERM -P $$ 2>/dev/null || true
    if [ -n "$CURRENT_LOCK_FILE" ]; then
        rm -f "$CURRENT_LOCK_FILE" 2>/dev/null || true
        CURRENT_LOCK_FILE=""
    fi
    if [ -n "$CURRENT_TASK_DIR" ] && [ -d "$CURRENT_TASK_DIR" ]; then
        cd "$topdir" 2>/dev/null || true
        local back="${CURRENT_TASK_DIR%__running}"
        mv "$CURRENT_TASK_DIR" "$back" 2>/dev/null || true
        local id="$CLAIMED_TASK_ID"
        if [ -z "$id" ]; then
            local bn
            bn="$(basename "$back")"
            id="${bn#mc}"
        fi
        [ -n "$id" ] && echo "$id" >> "$Q_RETRY"
    fi
    mark_clear
    exit 128
}

trap cleanup_trap TERM INT QUIT
trap mark_clear EXIT

# ============ 主执行循环 ============
echo "开始执行 RASPA3 模拟计算..."
echo "工作目录: ${topdir}"
echo "子目录: ${subdir}"
echo "当前CPU核心ID: ${CPU}"
echo "总CPU核心数: ${TOTAL_CPUS}"
echo "Conda环境: ${RASPA3_CONDA_ENV}"
ensure_queue

if [ -f "$Q_LAST" ]; then
    last_show=$(cat "$Q_LAST")
else
    if [ "$LIST_MODE" -eq 1 ]; then
        last_show=$(awk 'END{print NR+0}' "$TASK_LIST" 2>/dev/null)
    else
        last_show=$(find "$topdir/$subdir" -maxdepth 1 -type d -name "mc[0-9]*" ! -name "*__*" 2>/dev/null | wc -l)
    fi
fi
echo "总任务上限(编号最大值): ${last_show}"

if SHOULD_EXIT_NOW; then
    echo "当前工人(${CPU})超过并发上限，退出。可用上限: $(read_limit || echo $TOTAL_CPUS)"
    exit 0
fi

while :; do
    if SHOULD_EXIT_NOW; then
        echo "检测到并发上限降低，工人(${CPU})停止领取新任务并退出"
        exit 0
    fi
    CLAIMED_TASK_DIR=""
    CLAIMED_TASK_ID=""
    CLAIMED_TASK_REL=""
    claim_from_retry || true
    if [ -z "$CLAIMED_TASK_DIR" ]; then
        claim_from_pointer || true
    fi
    if [ -z "$CLAIMED_TASK_DIR" ]; then
        curr=$(awk 'NR==1{print $1; exit}' "$Q_NEXT" 2>/dev/null)
        last=$(awk 'NR==1{print $1; exit}' "$Q_LAST" 2>/dev/null)
        [ -z "$curr" ] && curr=0
        [ -z "$last" ] && last=0
        if [ "$curr" -gt "$last" ]; then
            now_epoch=$(date +%s)
            if [ $((now_epoch - LAST_RESCAN_EPOCH)) -ge "$QUEUE_RESCAN_INTERVAL_SECONDS" ] 2>/dev/null; then
                LAST_RESCAN_EPOCH="$now_epoch"
                if rescan_pending; then
                    continue
                fi
            fi
            if [ ! -s "$Q_RETRY" ]; then
                break
            fi
        fi
        sleep 0.2
        continue
    fi

    task_running_dir="$CLAIMED_TASK_DIR"
    task_id="$CLAIMED_TASK_ID"
    task_rel="$CLAIMED_TASK_REL"
    cd "$task_running_dir" || { cd "$topdir"; continue; }
    bn=$(basename "$task_running_dir")
    if [ -n "$task_rel" ]; then
        display_name="$task_rel"
    else
        mcid="${bn%__running}"
        display_name="mc${mcid#mc}"
    fi
    mark_start "$task_running_dir" "$display_name"

    # ============ RASPA3 执行命令 ============
    # RASPA3 直接执行 raspa3 命令（不需要参数，会自动读取 simulation.json）
    raspa3
    RASPA3_EXIT_CODE=$?

    # RASPA3 成功判断：检查 output/ 目录是否存在且包含输出文件
    # 注意：RASPA3 可能返回非零退出码即使计算成功完成
    OUTPUT_FILES_COUNT=$(find output -maxdepth 1 -type f \( -name "output_*.txt" -o -name "output_*.json" \) 2>/dev/null | wc -l)

    if [ -d "output" ] && [ "$OUTPUT_FILES_COUNT" -gt 0 ]; then
        # 有输出文件，视为成功；如启用 pyMSER 则先自动续跑判定平衡
        mser_status=0
        if [ "${RASPA_MSER_ENABLE}" = "true" ] && [ -d "$MSER_PYTHONPATH/raspa_calc/algorithms" ]; then
            echo " ==> 运行 pyMSER 自动平衡: ${display_name}"
            MSER_ARGS=()
            if [ -n "${RASPA_MSER_LLM:-}" ]; then
                case "${RASPA_MSER_LLM}" in
                    false|0|no|n) MSER_ARGS+=("--no-llm");;
                    *) MSER_ARGS+=("--llm");;
                esac
            fi
            [ -n "${RASPA_MSER_BATCH_SIZE:-}" ] && MSER_ARGS+=("--batch-size" "${RASPA_MSER_BATCH_SIZE}")
            if command -v conda >/dev/null 2>&1; then
                conda run -n "${RASPA_MSER_CONDA_ENV:-pymser}" python -m "$MSER_MODULE" \
                  --workdir "$(pwd)" \
                  --target-cycles "${RASPA_MSER_TARGET_CYCLES:-1000}" \
                  --add-cycles "${RASPA_MSER_ADD_CYCLES:-500}" \
                  --max-iter "${RASPA_MSER_MAX_ITER:-20}" \
                  --uncertainty "${RASPA_MSER_UNCERTAINTY:-uSD}" \
                  --conda-env "${RASPA_MSER_CONDA_ENV:-pymser}" \
                  --raspa3-conda-env "${RASPA3_CONDA_ENV:-raspa3}" \
                  "${MSER_ARGS[@]}"
            else
                python3 -m "$MSER_MODULE" \
                  --workdir "$(pwd)" \
                  --target-cycles "${RASPA_MSER_TARGET_CYCLES:-1000}" \
                  --add-cycles "${RASPA_MSER_ADD_CYCLES:-500}" \
                  --max-iter "${RASPA_MSER_MAX_ITER:-20}" \
                  --uncertainty "${RASPA_MSER_UNCERTAINTY:-uSD}" \
                  --conda-env "${RASPA_MSER_CONDA_ENV:-pymser}" \
                  --raspa3-conda-env "${RASPA3_CONDA_ENV:-raspa3}" \
                  "${MSER_ARGS[@]}"
            fi
            mser_status=$?
            if [ -f "mser_status.txt" ]; then
                mser_note=$(head -n 1 "mser_status.txt" | tr -d '\r')
                if [ -n "$mser_note" ]; then
                    echo " ==> < pyMSER 状态 > ${display_name}: ${mser_note}" >> ${LOGFILE}
                fi
            fi
            if [ $mser_status -ne 0 ]; then
                echo " ==> < pyMSER 平衡失败 > in directory ${display_name} on core (${thiscore}) (标记失败，查看auto_mser.log)" >> ${LOGFILE}
            fi
        fi

        if [ $mser_status -ne 0 ]; then
            mv "${task_running_dir}" "${task_running_dir%__running}__failed"
        else
            mv "${task_running_dir}" "${task_running_dir%__running}__done"
            FRAMEWORK_NAME=$(python3 -c "import json; print(json.load(open('simulation.json'))['Systems'][0]['Name'].split('/')[-1])" 2>/dev/null)
            [ -z "$FRAMEWORK_NAME" ] && FRAMEWORK_NAME="${display_name}"
            echo " ==> < ${FRAMEWORK_NAME} > is just done on core (${thiscore})." >> ${LOGFILE}
        fi
    else
        # 没有输出文件，视为失败
        mv "${task_running_dir}" "${task_running_dir%__running}__failed"
        echo " ==> < RASPA3 模拟失败 > in directory ${display_name} on core (${thiscore}). Exit code: ${RASPA3_EXIT_CODE}" >> ${LOGFILE}
    fi

    CURRENT_TASK_DIR=""
    mark_clear
    cd "${topdir}"
done

echo "所有 RASPA3 模拟计算任务已完成"
