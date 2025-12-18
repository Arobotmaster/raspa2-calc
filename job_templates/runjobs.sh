#!/bin/bash

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
CWD="$(pwd -P)"
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
mkdir -p "$QDIR"

ensure_queue() {
  if [ ! -f "$Q_NEXT" ] || [ ! -f "$Q_LAST" ]; then
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
    local workdir="${topdir}/${subdir}/mc${id}"
    # 已完成的任务不再写回重试队列
    if [ -d "${workdir}__done" ] || [ -d "${workdir}__failed" ] || [ -d "${workdir}__running" ]; then
      continue
    fi
    if [ -d "$workdir" ]; then
      local lock_file="${workdir}.lock"
      if (set -o noclobber; echo "$$" > "$lock_file") 2>/dev/null; then
        if [ -f "${workdir}/simulation.input" ]; then
          if mv "$workdir" "${workdir}__running"; then
            rm -f "$lock_file"
            echo "${workdir}__running"
            claimed="yes"
            # 将剩余未处理的 pending_ids 写回
            for pid in "${pending_ids[@]}"; do
              echo "$pid" >> "$Q_RETRY"
            done
            break
          else
            rm -f "$lock_file"
          fi
        else
          rm -f "$lock_file"
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

    local workdir="${topdir}/${subdir}/mc${id}"
    if [ ! -d "$workdir" ]; then
      continue
    fi
    if [ -d "${workdir}__done" ] || [ -d "${workdir}__failed" ] || [ -d "${workdir}__running" ]; then
      continue
    fi
    local lock_file="${workdir}.lock"
    if (set -o noclobber; echo "$$" > "$lock_file") 2>/dev/null; then
      if [ -f "${workdir}/simulation.input" ]; then
        if mv "$workdir" "${workdir}__running"; then
          rm -f "$lock_file"
          echo "${workdir}__running"
          return 0
        else
          rm -f "$lock_file"
        fi
      else
        rm -f "$lock_file"
      fi
    fi
  done
}

rescan_pending() {
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
  if [ -n "$CURRENT_TASK_DIR" ] && [ -d "$CURRENT_TASK_DIR" ]; then
    cd "$topdir" 2>/dev/null || true
    local back="${CURRENT_TASK_DIR%__running}"
    mv "$CURRENT_TASK_DIR" "$back" 2>/dev/null || true
    local bn
    bn="$(basename "$back")"
    local id="${bn#mc}"
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
  last_show=$(find "$topdir/$subdir" -maxdepth 1 -type d -name "mc[0-9]*" ! -name "*__*" 2>/dev/null | wc -l)
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
  task_running_dir=""
  task_running_dir=$(claim_from_retry) || true
  if [ -z "$task_running_dir" ]; then
    task_running_dir=$(claim_from_pointer) || true
  fi
  if [ -z "$task_running_dir" ]; then
    curr=$(awk 'NR==1{print $1; exit}' "$Q_NEXT" 2>/dev/null)
    last=$(awk 'NR==1{print $1; exit}' "$Q_LAST" 2>/dev/null)
    [ -z "$curr" ] && curr=0
    [ -z "$last" ] && last=0
    if [ "$curr" -gt "$last" ] && [ ! -s "$Q_RETRY" ]; then
      if rescan_pending; then
        continue
      fi
      break
    fi
    sleep 0.2
    continue
  fi
  cd "$task_running_dir" || { cd "$topdir"; continue; }
  bn=$(basename "$task_running_dir")
  mcid="${bn%__running}"
  mid=${mcid#mc}
  mark_start "$task_running_dir" "mc${mid}"
  eval $SIMULATE_CMD
  if [ $? -ne 0 ]; then
    mv "${task_running_dir}" "${topdir}/${subdir}/mc${mid}__failed"
    echo " ==> < 模拟失败 > in directory mc${mid} on core (${thiscore})." >> ${LOGILFE}
  else
    mv "${task_running_dir}" "${topdir}/${subdir}/mc${mid}__done"
    FRAMEWORK_NAME=$(grep "FrameworkName" simulation.input 2>/dev/null | awk '{print $2}')
    [ -z "$FRAMEWORK_NAME" ] && FRAMEWORK_NAME="mc${mid}"
    echo " ==> < ${FRAMEWORK_NAME} > is just done on core (${thiscore})." >> ${LOGILFE}
  fi
  CURRENT_TASK_DIR=""
  mark_clear
  cd "${topdir}"
done

echo "所有模拟计算任务已完成"
