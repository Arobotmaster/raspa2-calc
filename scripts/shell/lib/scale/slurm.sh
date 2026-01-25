#!/bin/bash

set -euo pipefail

slurm_autoscale() {
# =========================
# SLURM: 自动扩缩容
# =========================
echo "$(ts) - INFO - 检测到 SLURM 调度器，开始自动扩缩容"
JOBS_FILE="$TARGET_DIR/.raspa_jobs.list"
WORKERS_DIR="$TARGET_DIR/.workers"
mkdir -p "$WORKERS_DIR"

submit_missing() {
  # 参数：逗号分隔的缺口编号列表，例如 "3,5,7"
  local missing_csv="$1"
  [ -z "$missing_csv" ] && return 0
  local LOG_DIR="$TARGET_DIR/1log"
  mkdir -p "$LOG_DIR"
  local SCRIPT_DIR="$ROOT_DIR/scripts/shell/templates/schedulers"
  local JOB_TEMPLATE="$SCRIPT_DIR/job_submit.sh"
  local TOOL_DIR="$ROOT_DIR"

  # slurmctld 只需要在提交时读取脚本；避免在 NFS 上反复 mktemp/cp/sed 写脚本导致提交变慢
  local submit_tmp_base
  submit_tmp_base="${RASPA_SUBMIT_TMP_BASE:-${TMPDIR:-/tmp}}"
  mkdir -p "$submit_tmp_base" 2>/dev/null || true

  local TMP_SCRIPT
  if TMP_SCRIPT=$(mktemp "${submit_tmp_base%/}/raspa2-calc.job_submit.XXXXXX.sh" 2>/dev/null); then
    :
  else
    TMP_SCRIPT=$(mktemp "/tmp/raspa2-calc.job_submit.XXXXXX.sh")
  fi
  cp -f "$JOB_TEMPLATE" "$TMP_SCRIPT"
  chmod 755 "$TMP_SCRIPT"

  local JOBS_BUF
  if JOBS_BUF=$(mktemp "${submit_tmp_base%/}/raspa2-calc.jobsbuf.XXXXXX" 2>/dev/null); then
    :
  else
    JOBS_BUF=$(mktemp "/tmp/raspa2-calc.jobsbuf.XXXXXX")
  fi
  : > "$JOBS_BUF"

  local submit_sleep
  submit_sleep="${RASPA_SCALE_SUBMIT_SLEEP:-${RASPA_SUBMIT_SLEEP:-0.15}}"
  local sbatch_retry
  sbatch_retry="${RASPA_SCALE_SBATCH_RETRY:-2}"
  if ! [[ "$sbatch_retry" =~ ^[0-9]+$ ]] || [ "$sbatch_retry" -lt 1 ]; then
    sbatch_retry=1
  fi
  local sbatch_retry_sleep
  sbatch_retry_sleep="${RASPA_SCALE_SBATCH_RETRY_SLEEP:-0.5}"

  local now
  now=$(date +%s)
  IFS=',' read -r -a arr <<< "$missing_csv"
  local total_workers=${#arr[@]}
  local submit_verbose=0
  case "${RASPA_SUBMIT_VERBOSE:-0}" in
    1|true|yes|y|on) submit_verbose=1 ;;
  esac
  local submit_every="${RASPA_SUBMIT_LOG_EVERY:-10}"
  if ! [[ "$submit_every" =~ ^[0-9]+$ ]] || [ "$submit_every" -le 0 ]; then
    submit_every=10
  fi
  if [ "$total_workers" -gt 0 ] && [ "$submit_every" -gt "$total_workers" ]; then
    submit_every="$total_workers"
  fi
  echo "开始逐个提交作业...（补交模式）"
  if [ "$submit_verbose" -eq 0 ] && [ "$submit_every" -gt 1 ]; then
    echo "提交中... 每 ${submit_every} 个任务提示一次 (完整输出可设 RASPA_SUBMIT_VERBOSE=1)"
  fi
  local -a plan_queue=()
  local plan_len=0
  # 若不存在节点计划，尝试基于集群信息和优先级生成
  if [ -z "$NODE_PLAN" ] && [ -n "$PY_RES_JSON" ] && [ "$NEW_LIMIT" -gt 0 ]; then
    NODE_PLAN=$(build_node_plan "$NEW_LIMIT" "$RASPA_NODE_PRIORITIES" "$PY_RES_JSON" "$NODE_PLAN_MODE")
  fi
  if [ -n "$NODE_PLAN" ]; then
    local PRIORITY_RAW="${RASPA_NODE_PRIORITIES:-}"
    # 构建 TPC_MAP 字符串供 Python 使用
    local TPC_MAP_STR=""
    for n in "${!NODE_TPC[@]}"; do
      TPC_MAP_STR+="${n}:${NODE_TPC[$n]},"
    done
    
    local py_out plan_queue_str plan_str_sorted
    py_out=$(NODE_PLAN_INPUT="$NODE_PLAN" PRIORITIES="$PRIORITY_RAW" TPC_MAP="$TPC_MAP_STR" python - <<'PY' 2>/dev/null || true
import os

plan = os.environ.get("NODE_PLAN_INPUT", "").strip()
prio_raw = os.environ.get("PRIORITIES", "").strip()
tpc_raw = os.environ.get("TPC_MAP", "").strip()

tpc_map = {}
for part in tpc_raw.split(','):
  if ':' not in part:
      continue
  n, v = part.split(':', 1)
  try:
      tpc_map[n.strip()] = int(v.strip())
  except:
      pass

entries = []
for part in plan.split(','):
  if not part or ':' not in part:
      continue
  node, count = part.split(':', 1)
  node = node.strip()
  try:
      cnt = int(count.strip())
  except Exception:
      continue
  if node and cnt > 0:
      entries.append((node, cnt))

priority = {}
for part in prio_raw.split(','):
  if ':' not in part:
      continue
  name, val = part.split(':', 1)
  name = name.strip()
  try:
      priority[name] = int(val.strip())
  except Exception:
      continue

if priority:
  entries = sorted(entries, key=lambda item: (-priority.get(item[0], 0), item[0]))

plan_str = ",".join(f"{n}:{c}" for n, c in entries)
queue = []
# 轮询展开，但保留打包亲和性（每次取 TPC 个）
entries_rr = [[n, c] for n, c in entries]
while True:
  added = False
  for item in entries_rr:
      if item[1] > 0:
          # 每次取 min(remain, tpc) 个，确保能打包
          node = item[0]
          tpc = tpc_map.get(node, 1)
          if tpc < 1: tpc = 1
          chunk = tpc if item[1] >= tpc else item[1]
          queue.extend([node] * chunk)
          item[1] -= chunk
          added = True
  if not added:
      break

print(plan_str)
print(" ".join(queue))
PY
)
    plan_str_sorted=$(printf "%s\n" "$py_out" | sed -n '1p')
    plan_queue_str=$(printf "%s\n" "$py_out" | sed -n '2p')
    if [ -z "$plan_queue_str" ]; then
      # 回退：按原始顺序展开并轮询分配，避免长串集中到单节点
      local -a plan_entries
      local -a plan_nodes
      declare -A plan_counts
      IFS=',' read -r -a plan_entries <<< "$NODE_PLAN"
      local entry node count
      for entry in "${plan_entries[@]}"; do
        node="${entry%%:*}"
        count="${entry#*:}"
        if [ -n "$node" ] && [[ "$count" =~ ^[0-9]+$ ]] && [ "$count" -gt 0 ]; then
          plan_nodes+=("$node")
          plan_counts["$node"]=$count
        fi
      done
      while :; do
        local added=0
        for node in "${plan_nodes[@]}"; do
          count=${plan_counts["$node"]:-0}
          if [ "$count" -gt 0 ]; then
            plan_queue+=("$node")
            plan_counts["$node"]=$((count-1))
            added=1
          fi
        done
        [ "$added" -eq 0 ] && break
      done
    else
      NODE_PLAN="${plan_str_sorted:-$NODE_PLAN}"
      read -r -a plan_queue <<< "$plan_queue_str"
    fi
    plan_len=${#plan_queue[@]}
  fi
  # 汇总节点计划（worker -> job），用于日志展示
  if [ "$plan_len" -gt 0 ]; then
    declare -A PLAN_WORKERS=() PLAN_JOBS=()
    for n in "${plan_queue[@]}"; do
      [ -n "$n" ] || continue
      PLAN_WORKERS["$n"]=$(( ${PLAN_WORKERS["$n"]:-0} + 1 ))
    done
    for n in "${!PLAN_WORKERS[@]}"; do
      tpc=${NODE_TPC["$n"]:-1}
      [ -z "$tpc" ] && tpc=1
      if ! [[ "$tpc" =~ ^[0-9]+$ ]]; then tpc=1; fi
      [ "$tpc" -lt 1 ] && tpc=1
      w=${PLAN_WORKERS["$n"]}
      jobs=$(( (w + tpc - 1) / tpc ))
      PLAN_JOBS["$n"]=$jobs
    done
    if [ ${#PLAN_JOBS[@]} -gt 0 ]; then
      plan_workers_str=""
      for n in "${!PLAN_WORKERS[@]}"; do
        plan_workers_str+="${n}:${PLAN_WORKERS[$n]},"
      done
      plan_jobs_str=""
      for n in "${!PLAN_JOBS[@]}"; do
        plan_jobs_str+="${n}:${PLAN_JOBS[$n]},"
      done
      plan_workers_str=${plan_workers_str%,}
      plan_jobs_str=${plan_jobs_str%,}
      echo "节点分配计划(线程->作业): ${plan_workers_str// /} -> ${plan_jobs_str// /}"
    fi
  fi

  local plan_index=0
  local job_base_dir
  local planned_jobs=0
  local idx=0
  local plan_strict=0
  if [ "$plan_len" -gt 0 ] && [ "$plan_len" -lt "$total_workers" ]; then
    plan_strict=1
    echo "提示: 节点计划容量(${plan_len})低于本次补交(${total_workers})，超出部分不强制节点"
  fi
  while [ $idx -lt $total_workers ]; do
    planned_jobs=$((planned_jobs + 1))
    TARGET_NODE=""
    local pack_size=1
    if [ "$SUBDIR" = "." ]; then
      job_base_dir="$TARGET_DIR"
    else
      job_base_dir="$(cd "$TARGET_DIR/.." && pwd -P)"
    fi
    if [ -n "$NODE_PLAN" ] && [ "$plan_len" -gt 0 ]; then
      if [ "$plan_strict" -eq 1 ] && [ $plan_index -ge $plan_len ]; then
        TARGET_NODE=""
      else
        if [ $plan_index -ge $plan_len ]; then
          plan_index=0
        fi
        TARGET_NODE="${plan_queue[$plan_index]}"
        if [ -n "$TARGET_NODE" ]; then
          pack_size=${NODE_TPC["$TARGET_NODE"]:-1}
          if ! [[ "$pack_size" =~ ^[0-9]+$ ]] || [ "$pack_size" -lt 1 ]; then
            pack_size=1
          fi
          # 确保不跨节点打包：仅在队列连续同节点时才使用 pack_size
          same_count=0
          while [ $((plan_index + same_count)) -lt $plan_len ] && [ "${plan_queue[$((plan_index + same_count))]}" = "$TARGET_NODE" ] && [ $same_count -lt $pack_size ]; do
            same_count=$((same_count + 1))
          done
          pack_size=$same_count
          [ "$pack_size" -lt 1 ] && pack_size=1
          # 跳过已消费的节点槽位
          plan_index=$((plan_index + pack_size))
          if [ $plan_index -ge $plan_len ] && [ "$plan_strict" -eq 0 ]; then
            plan_index=0
          fi
        fi
      fi
    fi
    # 剩余 worker 不足时降级 pack_size
    remaining=$((total_workers - idx))
    if [ "$pack_size" -gt "$remaining" ]; then
      pack_size="$remaining"
    fi

    # 取本作业的 worker ID 列表
    local -a WORKER_IDS=()
    for ((j=0; j<pack_size; j++)); do
      WORKER_IDS+=("${arr[$((idx + j))]}")
    done
    local WORKER_IDS_CSV
    WORKER_IDS_CSV=$(IFS=,; echo "${WORKER_IDS[*]}")
    local NAMENEW="${WORKER_IDS[0]}"
    local last_wid="${WORKER_IDS[$((pack_size - 1))]}"
    local next_idx=$((idx + pack_size))
    if [ "$submit_verbose" -eq 1 ]; then
      echo "正在提交第${last_wid}个任务…"
    else
      if [ "$next_idx" -eq "$pack_size" ] || [ "$next_idx" -eq "$total_workers" ] || [ $((next_idx % submit_every)) -eq 0 ]; then
        echo "正在提交第${last_wid}个任务…"
      fi
    fi
    local -a SBATCH_EXTRA_ARGS=()
    if [ "$pack_size" -gt 1 ]; then
      SBATCH_EXTRA_ARGS+=(--cpus-per-task="$pack_size")
    fi

    # 提交（强制日志到 1log）
    out="$LOG_DIR/${NAMENEW}.out"; err="$LOG_DIR/${NAMENEW}.err"
    local submit_ok=0
    local submit_result=""
    local jid=""
    local attempt=1
    while :; do
      if [ -n "$TARGET_NODE" ]; then
        submit_result=$(
          RASPA_TOTAL_CPUS="${NEW_LIMIT}" \
          RASPA_WORK_DIR="${job_base_dir}" \
          RASPA_OUTPUT_DIR="${SUBDIR}" \
          RASPA_SUBDIR="${SUBDIR}" \
          RASPA_WORKER_ID="${NAMENEW}" \
          RASPA_WORKER_IDS="${WORKER_IDS_CSV}" \
          RASPA_VERSION="${RASPA_VERSION:-raspa2}" \
          RASPA_TOOL_DIR="${TOOL_DIR}" \
          sbatch --export=ALL "${SBATCH_EXTRA_ARGS[@]}" --nodelist="$TARGET_NODE" -J "$NAMENEW" -o "$out" -e "$err" "$TMP_SCRIPT" 2>&1 || true
        )
      else
        submit_result=$(
          RASPA_TOTAL_CPUS="${NEW_LIMIT}" \
          RASPA_WORK_DIR="${job_base_dir}" \
          RASPA_OUTPUT_DIR="${SUBDIR}" \
          RASPA_SUBDIR="${SUBDIR}" \
          RASPA_WORKER_ID="${NAMENEW}" \
          RASPA_WORKER_IDS="${WORKER_IDS_CSV}" \
          RASPA_VERSION="${RASPA_VERSION:-raspa2}" \
          RASPA_TOOL_DIR="${TOOL_DIR}" \
          sbatch --export=ALL "${SBATCH_EXTRA_ARGS[@]}" -J "$NAMENEW" -o "$out" -e "$err" "$TMP_SCRIPT" 2>&1 || true
        )
      fi
      if [[ "$submit_result" =~ Submitted\ batch\ job\ ([0-9]+) ]]; then
        submit_ok=1
        jid="${BASH_REMATCH[1]}"
        printf "%s %s %s %s\n" "$jid" "$NAMENEW" "$now" "$WORKER_IDS_CSV" >> "$JOBS_BUF"
        break
      fi
      if [ "$attempt" -ge "$sbatch_retry" ]; then
        break
      fi
      if [ -n "$sbatch_retry_sleep" ] && [[ "$sbatch_retry_sleep" =~ ^[0-9]+([.][0-9]+)?$ ]] && [ "$sbatch_retry_sleep" != "0" ] && [ "$sbatch_retry_sleep" != "0.0" ]; then
        sleep "$sbatch_retry_sleep"
      fi
      attempt=$((attempt + 1))
    done
    if [ "$submit_verbose" -eq 1 ]; then
      echo "$submit_result"
      if [ "$submit_ok" -eq 1 ]; then
        echo "✅ 作业 $NAMENEW 提交完成"
      fi
    else
      if [ "$submit_ok" -eq 0 ]; then
        echo "$submit_result"
      fi
    fi
    idx=$((idx + pack_size))
    if [ -n "$submit_sleep" ] && [[ "$submit_sleep" =~ ^[0-9]+([.][0-9]+)?$ ]] && [ "$submit_sleep" != "0" ] && [ "$submit_sleep" != "0.0" ]; then
      sleep "$submit_sleep"
    fi
  done
  local submitted_jobs=0
  submitted_jobs=$(wc -l < "$JOBS_BUF" 2>/dev/null || echo 0)
  echo "提交汇总: worker=${total_workers}, 计划SLURM作业=${planned_jobs}, 成功提交作业=${submitted_jobs}"

  # 批量追加 .raspa_jobs.list，减少 NFS 元数据压力
  if [ -s "$JOBS_BUF" ]; then
    {
      exec 9>>"$JOBS_FILE"
      flock -n 9 || true
      cat "$JOBS_BUF" >&9
      flock -u 9 || true
      exec 9>&-
    }
  fi
  rm -f "$JOBS_BUF" 2>/dev/null || true
  rm -f "$TMP_SCRIPT" 2>/dev/null || true
}

# 读取当前活跃作业列表，并估算活跃 worker 数
LIVE=0
LIST_FILE="$TARGET_DIR/.raspa_queue/tasks.list"
LIST_MODE=0
if [ -f "$LIST_FILE" ] && grep -q '[^[:space:]]' "$LIST_FILE" 2>/dev/null; then
  LIST_MODE=1
fi
if [ "$LIST_MODE" -eq 1 ]; then
  INITIAL_RUNNING=$(LIST_FILE="$LIST_FILE" TARGET_DIR="$TARGET_DIR" python - <<'PY' 2>/dev/null || true
import os

base = os.environ.get("TARGET_DIR", "")
list_file = os.environ.get("LIST_FILE", "")
count = 0
if base and list_file and os.path.isfile(list_file):
    try:
        with open(list_file, "r", encoding="utf-8") as fh:
            for line in fh:
                rel = line.strip()
                if not rel:
                    continue
                run_path = os.path.join(base, rel.rstrip("/")) + "__running"
                if os.path.isdir(run_path):
                    count += 1
    except Exception:
        pass
print(count)
PY
  )
else
  INITIAL_RUNNING=$(find "$TARGET_DIR" -maxdepth 1 -type d -name 'mc*__running' 2>/dev/null | wc -l | awk '{print $1}' || true)
fi
if ! [[ "${INITIAL_RUNNING:-}" =~ ^[0-9]+$ ]]; then
  INITIAL_RUNNING=0
fi
ACTIVE_FILE="$WORKERS_DIR/.active_jobs.tsv"
ACTIVE_WORKERS_FILE="$WORKERS_DIR/.active_workers.list"
: > "$ACTIVE_FILE"
: > "$ACTIVE_WORKERS_FILE"
SQUEUE_OK=0
if command -v squeue >/dev/null 2>&1; then
  if squeue -u "$USER" -h -o "%i" >/dev/null 2>&1; then
    SQUEUE_OK=1
  fi
fi
if [ "$SQUEUE_OK" -eq 1 ]; then
  PY_TARGET="$TARGET_DIR" PY_USER="$USER" python - <<'PY' 2>/dev/null > "$ACTIVE_FILE" || true
import os, subprocess, sys

target = os.environ.get("PY_TARGET", "").rstrip("/") + "/"
user = os.environ.get("PY_USER", "")
if not target or not user:
  sys.exit(0)

try:
  out = subprocess.check_output(
      ["squeue", "-u", user, "-h", "-O", "jobid:20,name:40,stdout:400"],
      stderr=subprocess.DEVNULL,
  ).decode(errors="ignore")
except Exception:
  sys.exit(0)

for raw in out.splitlines():
  parts = raw.strip().split(None, 2)
  if len(parts) < 3:
      continue
  jid, name, stdout = parts[0], parts[1], parts[2]
  if stdout.startswith(target):
      print(f"{jid} {name} {stdout}")
PY
fi
LIVE_WORKERS=0
LIVE_JOBS=0
EXPANDED_THIS_ROUND=0
if [ -s "$ACTIVE_FILE" ]; then
  LIVE_JOBS=$(wc -l < "$ACTIVE_FILE" 2>/dev/null || echo 0)
  LIVE=$(wc -l < "$ACTIVE_FILE" 2>/dev/null || echo 0)
  LIVE_WORKERS=$(ACTIVE_PATH="$ACTIVE_FILE" JOBS_PATH="$JOBS_FILE" DUMP_PATH="$ACTIVE_WORKERS_FILE" python - <<'PY' 2>/dev/null || true
import os, re

active_path = os.environ.get("ACTIVE_PATH", "")
jobs_path = os.environ.get("JOBS_PATH", "")
dump_path = os.environ.get("DUMP_PATH", "")
csv_re = re.compile(r"^[0-9]+(,[0-9]+)*$")

job_map = {}
if jobs_path and os.path.exists(jobs_path):
  with open(jobs_path, "r", encoding="utf-8") as fh:
      for raw in fh:
          parts = raw.strip().split()
          if len(parts) < 2:
              continue
          jid = parts[0]
          worker_csv = parts[3] if len(parts) >= 4 else ""
          job_map[jid] = worker_csv or parts[1]

ids = set()
if active_path and os.path.exists(active_path):
  with open(active_path, "r", encoding="utf-8") as fh:
      for raw in fh:
          parts = raw.strip().split()
          if len(parts) < 2:
              continue
          jid, name = parts[0], parts[1]
          csv_val = job_map.get(jid, "")
          if csv_val and csv_re.match(csv_val):
              ids.update(int(x) for x in csv_val.split(",") if x.isdigit())
          elif name.isdigit():
              ids.add(int(name))
if dump_path:
  try:
      with open(dump_path, "w", encoding="utf-8") as fh:
          for i in sorted(ids):
              fh.write(f"{i}\n")
  except Exception:
      pass
print(len(ids))
PY
  )
fi
# 若过滤列表为空，则回退到 .raspa_jobs 与 squeue 的交集估计
if [ "$LIVE" -le 0 ] && [ -f "$JOBS_FILE" ] && [ "$SQUEUE_OK" -eq 1 ]; then
  mapfile -t ALL_MY_JOBS < <(squeue -u "$USER" -h -o "%i" 2>/dev/null | sort -u || true)
  mapfile -t TRACKED < <(awk '{print $1}' "$JOBS_FILE" | sort -u || true)
  if [ ${#ALL_MY_JOBS[@]} -gt 0 ] && [ ${#TRACKED[@]} -gt 0 ]; then
    LIVE=$(comm -12 <(printf "%s\n" "${ALL_MY_JOBS[@]}") <(printf "%s\n" "${TRACKED[@]}" ) | wc -l || true)
    if ! [[ "${LIVE:-}" =~ ^[0-9]+$ ]]; then
      LIVE=0
    fi
  fi
fi
# 若仍为0，则用 __running 目录兜底；否则优先使用 worker 计数
if [ "$LIVE_WORKERS" -gt 0 ]; then
  LIVE=$LIVE_WORKERS
elif [ "$SQUEUE_OK" -eq 0 ] && [ "$INITIAL_RUNNING" -gt "$LIVE" ]; then
  LIVE=$INITIAL_RUNNING
fi
# 补充 worker 计数，确保后续缩容按“实际 worker 数”计算
if [ "$LIVE_WORKERS" -le 0 ] && [ "$LIVE" -gt 0 ]; then
  LIVE_WORKERS="$LIVE"
fi
TOTAL_LIVE_WORKERS="$LIVE_WORKERS"

# 若调度器未发现任何相关作业，但目录中仍有 __running 标记，视为孤儿并恢复为待处理
if [ "$SQUEUE_OK" -eq 1 ] && [ "$LIVE_WORKERS" -eq 0 ] && [ "$LIVE_JOBS" -eq 0 ]; then
  if [ "$LIST_MODE" -eq 1 ]; then
    mapfile -t ORPHAN_DIRS < <(LIST_FILE="$LIST_FILE" TARGET_DIR="$TARGET_DIR" python - <<'PY' 2>/dev/null || true
import os
import time

base = os.environ.get("TARGET_DIR", "")
list_file = os.environ.get("LIST_FILE", "")
cutoff = time.time() - 180
paths = []
if base and list_file and os.path.isfile(list_file):
    try:
        with open(list_file, "r", encoding="utf-8") as fh:
            for line in fh:
                rel = line.strip()
                if not rel:
                    continue
                run_path = os.path.join(base, rel.rstrip("/")) + "__running"
                if not os.path.isdir(run_path):
                    continue
                try:
                    mtime = os.path.getmtime(run_path)
                except Exception:
                    continue
                if mtime <= cutoff:
                    paths.append(run_path)
    except Exception:
        pass
for p in sorted(paths):
    print(p)
PY
    )
  else
    mapfile -t ORPHAN_DIRS < <(find "$TARGET_DIR" -maxdepth 1 -type d -name 'mc*__running' -mmin +3 2>/dev/null | sort || true)
  fi
  if [ ${#ORPHAN_DIRS[@]} -gt 0 ]; then
    echo "提示: 检测到 ${#ORPHAN_DIRS[@]} 个 __running 目录未对应调度作业，自动恢复为待处理以继续补交。"
    ts=$(date +%s)
    for d in "${ORPHAN_DIRS[@]}"; do
      base="${d%__running}"
      if [ ! -e "$base" ]; then
        mv "$d" "$base" 2>/dev/null || true
      else
        mv "$d" "${base}__orphan_${ts}" 2>/dev/null || true
      fi
    done
  fi
fi

# 如未启用作业追踪文件，则仅写入上限，不做自动提交/缩容（避免错误扩容）
if [ ! -s "$JOBS_FILE" ]; then
  echo "提示: 未发现 $JOBS_FILE，尝试基于 scontrol 的 StdOut 路径重建..." >&2
  LOGDIR_CAND="$(find "$TARGET_DIR" -maxdepth 2 -type d -name 1log -print -quit 2>/dev/null || true)"
  # 若当前目录就是子目录，默认日志在 ./1log
  [ -z "$LOGDIR_CAND" ] && LOGDIR_CAND="$TARGET_DIR/1log"
  touch "$JOBS_FILE"
  if [ "$SQUEUE_OK" -eq 1 ] && command -v scontrol >/dev/null 2>&1; then
    # 遍历当前用户的运行中/排队中的作业，筛选 StdOut 在本子目录下的
    while IFS= read -r jid; do
      [ -n "$jid" ] || continue
      sd=$(scontrol show job "$jid" 2>/dev/null | awk -F= '/StdOut=/{print $2}' | awk '{print $1}' | head -1 || true)
      jn=$(scontrol show job "$jid" 2>/dev/null | awk -F= '/JobName=/{print $2}' | awk '{print $1}' | head -1 || true)
      if [ -n "$sd" ] && [[ "$sd" == $TARGET_DIR/* ]] ; then
        echo "$jid ${jn:-0} $(date +%s)" >> "$JOBS_FILE"
      fi
    done < <(squeue -u "$USER" -h -o "%i" 2>/dev/null || true)
  else
    echo "提示: squeue 或 scontrol 不可用，跳过作业重建" >&2
  fi
  if [ ! -s "$JOBS_FILE" ]; then
    echo "提示: 仍无法识别本批次的 SLURM 作业，跳过自动补交/缩容（仅更新上限）" >&2
  else
    echo "已重建 $JOBS_FILE，共识别 $(wc -l < "$JOBS_FILE") 个作业" >&2
  fi
fi
if false; then
echo "检测到 PBS 环境：执行目录内的自动扩缩容逻辑"
WORKERS_DIR="$TARGET_DIR/.workers"
mkdir -p "$WORKERS_DIR"

# 读取当前目录内活跃工人编号（.workers 下的纯数字文件名）
mapfile -t PRESENT_IDS < <(find "$WORKERS_DIR" -maxdepth 1 -type f -printf '%f\n' 2>/dev/null | awk '/^[0-9]+$/ {print $1}' | sort -n)
LIVE=${#PRESENT_IDS[@]}

# 统计待处理任务，用于避免过度扩容
scan_task_counts "$TARGET_DIR"
TOTAL_AVAILABLE=$((RUNNING_COUNT + PENDING_COUNT))

# 需要扩容的数量（不超过可用任务与目标差值）
NEED=$((NEW_LIMIT - LIVE))
if [ "$NEED" -lt 0 ]; then NEED=0; fi
GAP=$((TOTAL_AVAILABLE - LIVE))
if [ "$GAP" -lt "$NEED" ]; then NEED=$GAP; fi

# 缩容：选择编号 > NEW_LIMIT 的工人，按本目录日志路径过滤后 qdel
if [ "$LIVE" -gt "$NEW_LIMIT" ]; then
  TO_KILL=$((LIVE - NEW_LIMIT))
  echo "缩容: 当前活跃=$LIVE, 目标=$NEW_LIMIT，将尝试终止 $TO_KILL 个作业（按编号>目标）"
  : > "$WORKERS_DIR/.kill_ids"
  for id in "${PRESENT_IDS[@]}"; do
    if [ "$id" -gt "$NEW_LIMIT" ] 2>/dev/null; then echo "$id" >> "$WORKERS_DIR/.kill_ids"; fi
  done
  mapfile -t PBS_LINES < <(qstat -u "$USER" 2>/dev/null | awk 'NR>2 && $1 ~ /\./ {print $1,$2}')
  for line in "${PBS_LINES[@]}"; do
    jid="${line%% *}"; name="${line#* }"
    if grep -qx "$name" "$WORKERS_DIR/.kill_ids" 2>/dev/null; then
      # 仅当 Output_Path/Error_Path 指向本目录日志时才杀
      if qstat -f "$jid" 2>/dev/null | grep -E "(Output_Path|Error_Path)\\s*=" | grep -q "$TARGET_DIR/1log/"; then
        echo "qdel $jid  (name=$name)"
        qdel "$jid" || true
      fi
    fi
  done
fi

# 扩容：为缺口编号补交作业（避免重复，仅提交 1..NEW_LIMIT 中缺失的编号）
if [ "$NEED" -gt 0 ]; then
  echo "扩容: 当前活跃=$LIVE, 目标=$NEW_LIMIT, 可用任务=${TOTAL_AVAILABLE}(运行中=${RUNNING_COUNT}, 待处理=${PENDING_COUNT})，计划补交 $NEED 个"
  MISSING_IDS=()
  for ((i=1;i<=NEW_LIMIT;i++)); do
    if ! printf '%s\n' "${PRESENT_IDS[@]}" | grep -qx "$i"; then
      MISSING_IDS+=("$i")
    fi
  done
  if [ ${#MISSING_IDS[@]} -gt "$NEED" ]; then
    MISSING_IDS=("${MISSING_IDS[@]:0:$NEED}")
  fi
  SCRIPT_DIR_TOOL="$ROOT_DIR/scripts/shell/entrypoints"
  SCRIPT_DIR_WORK="$BASE_DIR/scripts/shell/entrypoints"
  RUNNER=""
  if [ -x "$SCRIPT_DIR_TOOL/submit.sh" ]; then
    RUNNER="$SCRIPT_DIR_TOOL/submit.sh"
  else
    RUNNER="$SCRIPT_DIR_WORK/submit.sh"
  fi
  for id in "${MISSING_IDS[@]}"; do
    echo "提交 worker 编号: $id"
    RASPA_WORK_DIR="$BASE_DIR" RASPA_SUBDIR="$SUBDIR" RASPA_OUTPUT_DIR="$SUBDIR" RASPA_START_ID="$id" RASPA_TOOL_DIR="$ROOT_DIR" \
      bash "$RUNNER" "$id" >/dev/null 2>&1 || true
  done
else
  echo "扩容: 当前活跃=$LIVE, 目标=$NEW_LIMIT, 可用任务=${TOTAL_AVAILABLE}，无需补交"
fi
fi
# 扩容：提交缺口（需要追踪文件）
SKIP_EXPAND=0
if [ "$LIVE_WORKERS" -ge "$NEW_LIMIT" ]; then
  SKIP_EXPAND=1
fi

if [ "$SKIP_EXPAND" -eq 0 ] && [ -s "$JOBS_FILE" ] && [ "$LIVE_WORKERS" -lt "$NEW_LIMIT" ]; then
  # 统计当前可并发的“有意义”上限：已在跑的任务数(__running) + 待处理的任务数(mc*)
  scan_task_counts "$TARGET_DIR"

  # 指针重置逻辑：如果有待处理任务但指针已耗尽，则删除指针以触发 Worker 重新扫描
  if [ "$PENDING_COUNT" -gt 0 ]; then
      q_next="$TARGET_DIR/.raspa_queue/next_id"
      q_last="$TARGET_DIR/.raspa_queue/last_id"
      if [ -f "$q_next" ] && [ -f "$q_last" ]; then
          curr_ptr=$(awk 'NR==1{print $1; exit}' "$q_next" 2>/dev/null)
          last_ptr=$(awk 'NR==1{print $1; exit}' "$q_last" 2>/dev/null)
          # 如果 next_id > last_id，说明队列已空。但 PENDING_COUNT > 0 说明有任务回滚了。
          if [ -n "$curr_ptr" ] && [ -n "$last_ptr" ] && [ "$curr_ptr" -gt "$last_ptr" ]; then
              echo "提示: 检测到 $PENDING_COUNT 个回滚任务且队列指针已耗尽 ($curr_ptr > $last_ptr)，自动重置指针以加速认领..."
              rm -f "$q_next"
          fi
      fi
  fi

  # “有意义”的目标并发 = min(用户目标, RUNNING + PENDING)
  USEFUL_TARGET=$NEW_LIMIT
  TOTAL_AVAILABLE=$((RUNNING_COUNT + PENDING_COUNT))
  if [ "$TOTAL_AVAILABLE" -lt "$USEFUL_TARGET" ]; then
    USEFUL_TARGET=$TOTAL_AVAILABLE
  fi

  # 计算现存 worker 集合，并找出 1..NEW_LIMIT 中缺口
  mapfile -t PRESENT_WORKERS < "$ACTIVE_WORKERS_FILE" 2>/dev/null || true
  if [ ${#PRESENT_WORKERS[@]} -eq 0 ]; then
    # 兜底：用 StdOut 过滤后的 job name（数字）推断
    mapfile -t PRESENT_WORKERS < <(awk '{print $2}' "$ACTIVE_FILE" 2>/dev/null | awk '/^[0-9]+$/{print $1}' | sort -n || true)
  fi
  present=""
  for wid in "${PRESENT_WORKERS[@]}"; do
    [ -n "$wid" ] && present+=" $wid"
  done
  missing_list=()
  for ((i=1;i<=NEW_LIMIT;i++)); do
    case " $present " in *" $i "*) : ;; *) missing_list+=("$i");; esac
  done

  # 本次最多需要补交的数量
  NEED=$((USEFUL_TARGET - LIVE_WORKERS))
  [ "$NEED" -lt 0 ] && NEED=0

  # 截断缺口到 NEED 个
  to_submit=()
  if [ "$NEED" -gt 0 ] && [ ${#missing_list[@]} -gt 0 ]; then
    for x in "${missing_list[@]}"; do
      [ "${#to_submit[@]}" -ge "$NEED" ] && break
      to_submit+=("$x")
    done
  fi

  if [ ${#to_submit[@]} -gt 0 ]; then
    IFS=',' read -r -a _dump <<< "${to_submit[*]}" # no-op to please shellcheck
    submit_csv=$(IFS=,; echo "${to_submit[*]}")
    echo "扩容: 当前活跃=${LIVE_WORKERS}, 目标=$NEW_LIMIT, 可用任务=${TOTAL_AVAILABLE}(运行中=${RUNNING_COUNT}, 待处理=${PENDING_COUNT})，计划补交worker=${#to_submit[@]}: ${submit_csv}"
    submit_missing "$submit_csv"
    EXPANDED_THIS_ROUND=1
  else
    echo "扩容: 当前活跃=${LIVE_WORKERS}, 目标=$NEW_LIMIT, 可用任务=${TOTAL_AVAILABLE}，无需补交"
  fi
fi

# 缩容：按实际 worker 数计算缺口，优先回收 worker_id 大于目标的作业
if [ -s "$JOBS_FILE" ] && [ "$LIVE_WORKERS" -gt "$NEW_LIMIT" ]; then
  EXCESS_WORKERS=$((LIVE_WORKERS - NEW_LIMIT))
  echo "缩容: 当前活跃=${LIVE_WORKERS} worker(作业=${LIVE_JOBS}), 目标=$NEW_LIMIT，需要释放约 ${EXCESS_WORKERS} worker"

  SKIP_SHRINK=0
  if [ "${RASPA_SCALE_KILL_FORCE:-0}" -ne 1 ]; then
    if [ -t 0 ]; then
      read -r -p "确认缩容并终止约 ${EXCESS_WORKERS} 个 worker 对应作业? [y/N]: " confirm
      if [[ ! "${confirm:-}" =~ ^[Yy]$ ]]; then
        echo "已取消缩容（未执行 scancel）。"
        SKIP_SHRINK=1
      fi
    else
      echo "提示: 非交互模式默认不执行缩容（可设置 RASPA_SCALE_KILL_FORCE=1 强制执行）"
      SKIP_SHRINK=1
    fi
  fi
  if [ "$SKIP_SHRINK" -eq 1 ]; then
    # 不缩容时直接跳过终止逻辑
    :
  else

  : > "$WORKERS_DIR/.kill_jobs"
  LIMIT_ENV="$NEW_LIMIT" EXCESS_ENV="$EXCESS_WORKERS" ACTIVE_PATH="$ACTIVE_FILE" JOBS_PATH="$JOBS_FILE" python - "$WORKERS_DIR/.kill_jobs" <<'PY'
import os, sys, re

limit = int(os.environ.get("LIMIT_ENV", "0") or 0)
excess = int(os.environ.get("EXCESS_ENV", "0") or 0)
active_path = os.environ.get("ACTIVE_PATH", "")
jobs_path = os.environ.get("JOBS_PATH", "")
out_path = sys.argv[1]
csv_re = re.compile(r"^[0-9]+(,[0-9]+)*$")

# jobid -> worker ids list
job_workers = {}
if jobs_path and os.path.exists(jobs_path):
  with open(jobs_path, "r", encoding="utf-8") as fh:
      for raw in fh:
          parts = raw.strip().split()
          if len(parts) < 2:
              continue
          jid, name = parts[0], parts[1]
          worker_csv = parts[3] if len(parts) >= 4 else ""
          ids = []
          if worker_csv and csv_re.match(worker_csv):
              ids = [int(x) for x in worker_csv.split(",") if x.isdigit()]
          elif name.isdigit():
              ids = [int(name)]
          job_workers[jid] = ids

active_jobs = []
if active_path and os.path.exists(active_path):
  with open(active_path, "r", encoding="utf-8") as fh:
      for raw in fh:
          parts = raw.strip().split()
          if len(parts) < 2:
              continue
          jid, name = parts[0], parts[1]
          ids = job_workers.get(jid, [])
          if not ids and name.isdigit():
              ids = [int(name)]
          if not ids:
              ids = [0]
          count = len(ids)
          min_id = min([x for x in ids if x > 0] or [10**9])
          all_gt_limit = all(x > limit for x in ids if x > 0)
          active_jobs.append(
              {
                  "jid": jid,
                  "ids": ids,
                  "count": count if count > 0 else 1,
                  "min_id": min_id,
                  "all_gt_limit": all_gt_limit,
              }
          )

if excess <= 0 or not active_jobs:
  sys.exit(0)

# 优先选择全部 worker_id 大于 limit 的作业，其次按最小 worker_id 由大到小
primary = [j for j in active_jobs if j["all_gt_limit"] or j["min_id"] > limit]
primary = sorted(primary, key=lambda j: j["min_id"], reverse=True)
rest = [j for j in active_jobs if j not in primary]
rest = sorted(rest, key=lambda j: j["min_id"], reverse=True)

selected = []
released = 0
for bucket in (primary, rest):
  for job in bucket:
      if released >= excess:
          break
      selected.append(job)
      released += job["count"]
  if released >= excess:
      break

# 若仍不足，以 JobId 倒序兜底
if released < excess:
  remaining = [j for j in active_jobs if j not in selected]
  remaining = sorted(remaining, key=lambda j: int(j["jid"]), reverse=True)
  for job in remaining:
      if released >= excess:
          break
      selected.append(job)
      released += job["count"]

with open(out_path, "w", encoding="utf-8") as fh:
  for job in selected:
      fh.write(f"{job['jid']}\n")
PY

  # 执行裁剪
  if [ -s "$WORKERS_DIR/.kill_jobs" ]; then
    KILL_WORKERS=$(ACTIVE_PATH="$ACTIVE_FILE" JOBS_PATH="$JOBS_FILE" KILL_PATH="$WORKERS_DIR/.kill_jobs" python - <<'PY' 2>/dev/null || true
import os, re

active_path = os.environ.get("ACTIVE_PATH", "")
jobs_path = os.environ.get("JOBS_PATH", "")
kill_path = os.environ.get("KILL_PATH", "")
csv_re = re.compile(r"^[0-9]+(,[0-9]+)*$")

job_workers = {}
if jobs_path and os.path.exists(jobs_path):
  with open(jobs_path, "r", encoding="utf-8") as fh:
      for raw in fh:
          parts = raw.strip().split()
          if len(parts) < 2:
              continue
          jid, name = parts[0], parts[1]
          worker_csv = parts[3] if len(parts) >= 4 else ""
          ids = []
          if worker_csv and csv_re.match(worker_csv):
              ids = [int(x) for x in worker_csv.split(",") if x.isdigit()]
          elif name.isdigit():
              ids = [int(name)]
          job_workers[jid] = ids

total = 0
if kill_path and os.path.exists(kill_path):
  with open(kill_path, "r", encoding="utf-8") as fh:
      for raw in fh:
          jid = raw.strip().split()[0]
          ids = job_workers.get(jid, [])
          total += len(ids) if ids else 1
print(total)
PY
    )
    while IFS= read -r jid; do
      [ -n "$jid" ] || continue
      echo "scancel $jid"
      scancel "$jid" || true
    done < "$WORKERS_DIR/.kill_jobs"
    KILL_COUNT=$(wc -l < "$WORKERS_DIR/.kill_jobs" 2>/dev/null || echo 0)
    echo "缩容: 已提交终止 ${KILL_COUNT} 个作业，预计释放 ${KILL_WORKERS:-?} 个 worker"

    # scancel 是异步的：刷新一次当前活跃 worker 统计，避免“过度缩容”后不回补
    SCANCEL_WAIT="${RASPA_SCALE_SCANCEL_WAIT:-2}"
    if [ -n "$SCANCEL_WAIT" ] && [[ "$SCANCEL_WAIT" =~ ^[0-9]+([.][0-9]+)?$ ]] && [ "$SCANCEL_WAIT" != "0" ] && [ "$SCANCEL_WAIT" != "0.0" ]; then
      sleep "$SCANCEL_WAIT"
    fi
    : > "$ACTIVE_FILE"
    : > "$ACTIVE_WORKERS_FILE"
    if [ "$SQUEUE_OK" -eq 1 ]; then
      PY_TARGET="$TARGET_DIR" PY_USER="$USER" python - <<'PY' 2>/dev/null > "$ACTIVE_FILE" || true
import os, subprocess, sys

target = os.environ.get("PY_TARGET", "").rstrip("/") + "/"
user = os.environ.get("PY_USER", "")
if not target or not user:
  sys.exit(0)

try:
  out = subprocess.check_output(
      ["squeue", "-u", user, "-h", "-O", "jobid:20,name:40,stdout:400"],
      stderr=subprocess.DEVNULL,
  ).decode(errors="ignore")
except Exception:
  sys.exit(0)

for raw in out.splitlines():
  parts = raw.strip().split(None, 2)
  if len(parts) < 3:
      continue
  jid, name, stdout = parts[0], parts[1], parts[2]
  if stdout.startswith(target):
      print(f"{jid} {name} {stdout}")
PY
    fi
    if [ -s "$ACTIVE_FILE" ]; then
      LIVE_JOBS=$(wc -l < "$ACTIVE_FILE" 2>/dev/null || echo 0)
      LIVE_WORKERS=$(ACTIVE_PATH="$ACTIVE_FILE" JOBS_PATH="$JOBS_FILE" DUMP_PATH="$ACTIVE_WORKERS_FILE" python - <<'PY' 2>/dev/null || true
import os, re

active_path = os.environ.get("ACTIVE_PATH", "")
jobs_path = os.environ.get("JOBS_PATH", "")
dump_path = os.environ.get("DUMP_PATH", "")
csv_re = re.compile(r"^[0-9]+(,[0-9]+)*$")

job_map = {}
if jobs_path and os.path.exists(jobs_path):
  with open(jobs_path, "r", encoding="utf-8") as fh:
      for raw in fh:
          parts = raw.strip().split()
          if len(parts) < 2:
              continue
          jid = parts[0]
          worker_csv = parts[3] if len(parts) >= 4 else ""
          job_map[jid] = worker_csv or parts[1]

ids = set()
if active_path and os.path.exists(active_path):
  with open(active_path, "r", encoding="utf-8") as fh:
      for raw in fh:
          parts = raw.strip().split()
          if len(parts) < 2:
              continue
          jid, name = parts[0], parts[1]
          csv_val = job_map.get(jid, "")
          if csv_val and csv_re.match(csv_val):
              ids.update(int(x) for x in csv_val.split(",") if x.isdigit())
          elif name.isdigit():
              ids.add(int(name))
if dump_path:
  try:
      with open(dump_path, "w", encoding="utf-8") as fh:
          for i in sorted(ids):
              fh.write(f"{i}\n")
  except Exception:
      pass
print(len(ids))
PY
      )
    fi
  else
    echo "缩容: 未找到可终止的作业条目（可能未在调度器中找到 StdOut 位于本目录的作业）。"
  fi
  fi
fi

# 缩容完成后如活跃数仍小于“有意义”的目标，按缺口补交
if [ "${LIVE_WORKERS:-0}" -gt "$NEW_LIMIT" ]; then
  echo "跳过补交：缩容请求处理中，当前活跃(${LIVE_WORKERS}) 仍高于目标(${NEW_LIMIT})。"
  exit 0
fi
if [ "$EXPANDED_THIS_ROUND" -eq 1 ]; then
  echo "补足并发: 本轮已完成扩容提交，等待调度器接管后再检查，无需重复提交。"
  exit 0
fi
mapfile -t PRESENT_WORKERS < "$ACTIVE_WORKERS_FILE" 2>/dev/null || true
if [ ${#PRESENT_WORKERS[@]} -eq 0 ]; then
  mapfile -t PRESENT_WORKERS < <(awk '{print $2}' "$ACTIVE_FILE" 2>/dev/null | awk '/^[0-9]+$/{print $1}' | sort -n || true)
fi
present=""
for wid in "${PRESENT_WORKERS[@]}"; do
  [ -n "$wid" ] && present+=" $wid"
done
# 现存活跃 worker 数
LIVE_COUNT=${#PRESENT_WORKERS[@]}
[ "$LIVE_COUNT" -le 0 ] && LIVE_COUNT="$LIVE_WORKERS"
# 重新估算“有意义”的目标并发（避免在无任务可跑时强行对齐用户上限）
scan_task_counts "$TARGET_DIR"
USEFUL_TARGET=$NEW_LIMIT
TOTAL_AVAILABLE=$((RUNNING_COUNT + PENDING_COUNT))
if [ "$TOTAL_AVAILABLE" -lt "$USEFUL_TARGET" ]; then
  USEFUL_TARGET=$TOTAL_AVAILABLE
fi

if [ "$LIVE_COUNT" -lt "$USEFUL_TARGET" ]; then
  # 构造缺口（1..NEW_LIMIT）
  missing_list=()
  for ((i=1;i<=NEW_LIMIT;i++)); do
    case " $present " in *" $i "*) : ;; *) missing_list+=("$i");; esac
  done
  NEED=$((USEFUL_TARGET - LIVE_COUNT))
  [ "$NEED" -lt 0 ] && NEED=0
  to_submit=()
  if [ "$NEED" -gt 0 ] && [ ${#missing_list[@]} -gt 0 ]; then
    for x in "${missing_list[@]}"; do
      [ "${#to_submit[@]}" -ge "$NEED" ] && break
      to_submit+=("$x")
    done
  fi
  if [ ${#to_submit[@]} -gt 0 ]; then
    submit_csv=$(IFS=,; echo "${to_submit[*]}")
    echo "补足并发: 现存=$LIVE_COUNT, 用户目标=$NEW_LIMIT, 可用任务=${TOTAL_AVAILABLE}(运行中=${RUNNING_COUNT}, 待处理=${PENDING_COUNT})，实际目标=${USEFUL_TARGET}，补交worker: ${submit_csv}"
    submit_missing "$submit_csv"
  else
    echo "补足并发: 现存=$LIVE_COUNT, 用户目标=$NEW_LIMIT, 可用任务=${TOTAL_AVAILABLE}，无需补交"
  fi
fi
}
