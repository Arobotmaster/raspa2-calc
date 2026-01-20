#!/bin/bash

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

emit("RASPA_DIR", env.get("raspa_dir"))
emit("RASPA_CIF_DIR", env.get("raspa2_cif_dir"))
emit("RASPA_TEMPLATE_PATH", env.get("template_path"))

mser = calc.get("mser") if isinstance(calc, dict) else {}
if isinstance(mser, dict):
    emit("RASPA_MSER_ENABLE", str(mser.get("enable", False)).lower())
    emit("RASPA_MSER_TARGET_CYCLES", mser.get("target_cycles"))
    emit("RASPA_MSER_ADD_CYCLES", mser.get("add_cycles"))
    emit("RASPA_MSER_MAX_ITER", mser.get("max_iter"))
    emit("RASPA_MSER_UNCERTAINTY", mser.get("uncertainty"))
    emit("RASPA_MSER_CONDA_ENV", mser.get("conda_env"))
PY
)"

# 检查环境
if [ -z "$RASPA_DIR" ]; then
  echo "错误：RASPA_DIR环境变量未设置"; exit 1
fi

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

# 使用当前真实工作目录（避免 $PWD 在目录被重命名后失效）
topdir="$CWD"
subdir=$(detect_subdir)
CPU=${1:-1}
TOTAL_CPUS=${2:-1}

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

thiscore=$$
LOGILFE=${topdir}/log__${subdir}_job_output
SIMULATE_CMD="$RASPA_DIR/bin/simulate"
[ -x "$SIMULATE_CMD" ] || SIMULATE_CMD="echo '模拟执行RASPA计算...'; sleep 2"
MSER_MODULE="raspa_calc.algorithms.auto_mser_raspa2"
MSER_PYTHONPATH="${RASPA_TOOL_DIR:-$HOME/raspa2-calc/.raspa_tools}/scripts/python"
export PYTHONPATH="${MSER_PYTHONPATH}${PYTHONPATH:+:$PYTHONPATH}"

# MSER 环境变量已在配置加载阶段尽可能设置；若仍未设置，则沿用已有环境或默认值
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
        if [ -f "${workdir}/simulation.input" ]; then
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
    # 兜底：若队列目录意外丢失（例如目录被临时重命名），重建之
    [ -d "$QDIR" ] || mkdir -p "$QDIR"
    # 打开队列锁，若失败则短暂等待后重试
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
      if [ -f "${workdir}/simulation.input" ]; then
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

echo "开始执行RASPA模拟计算..."
echo "工作目录: ${topdir}"
echo "子目录: ${subdir}"
echo "当前CPU核心ID: ${CPU}"
echo "总CPU核心数: ${TOTAL_CPUS}"
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
echo "RASPA目录: ${RASPA_DIR}"

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
  eval $SIMULATE_CMD
  if [ $? -ne 0 ]; then
    mv "${task_running_dir}" "${task_running_dir%__running}__failed"
    echo " ==> < 模拟失败 > in directory ${display_name} on core (${thiscore})." >> ${LOGILFE}
  else
    if [ "${RASPA_MSER_ENABLE}" = "true" ] && [ -d "$MSER_PYTHONPATH/raspa_calc/algorithms" ]; then
      echo " ==> 运行 pyMSER 自动平衡: ${display_name}"
      # 优先使用 conda run，避免非交互激活失败
      if command -v conda >/dev/null 2>&1; then
        conda run -n "${RASPA_MSER_CONDA_ENV:-pymser}" python -m "$MSER_MODULE" \
          --workdir "$(pwd)" \
          --target-cycles "${RASPA_MSER_TARGET_CYCLES:-1000}" \
          --add-cycles "${RASPA_MSER_ADD_CYCLES:-500}" \
          --max-iter "${RASPA_MSER_MAX_ITER:-20}" \
          --uncertainty "${RASPA_MSER_UNCERTAINTY:-uSD}" \
          --conda-env "${RASPA_MSER_CONDA_ENV:-pymser}"
      else
        python -m "$MSER_MODULE" \
          --workdir "$(pwd)" \
          --target-cycles "${RASPA_MSER_TARGET_CYCLES:-1000}" \
          --add-cycles "${RASPA_MSER_ADD_CYCLES:-500}" \
          --max-iter "${RASPA_MSER_MAX_ITER:-20}" \
          --uncertainty "${RASPA_MSER_UNCERTAINTY:-uSD}" \
          --conda-env "${RASPA_MSER_CONDA_ENV:-pymser}"
      fi
      if [ $? -ne 0 ]; then
        echo " ==> < pyMSER 平衡失败 > in directory ${display_name} on core (${thiscore}) (自动跳过，查看auto_mser.log)" >> ${LOGILFE}
      fi
    fi
    mv "${task_running_dir}" "${task_running_dir%__running}__done"
    FRAMEWORK_NAME=$(grep "FrameworkName" simulation.input 2>/dev/null | awk '{print $2}')
    [ -z "$FRAMEWORK_NAME" ] && FRAMEWORK_NAME="${display_name}"
    echo " ==> < ${FRAMEWORK_NAME} > is just done on core (${thiscore})." >> ${LOGILFE}
  fi
  CURRENT_TASK_DIR=""
  mark_clear
  cd "${topdir}"
done

echo "所有模拟计算任务已完成"
