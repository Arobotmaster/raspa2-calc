#!/bin/bash

set -euo pipefail

fetch_cluster_info_json() {
  PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
    python -m raspa_calc.domain.algorithms.cluster_info 2>/dev/null || true
}

collect_cluster_info() {
  USEFUL_TASKS=$((RUNNING_COUNT + PENDING_COUNT))

  CL_TOTAL=0; CL_ALLOC=0; CL_OTHER=0; CL_IDLE=0
  CL_METHOD="none"
  CL_NODE_LINES=()
  NODE_TPC=()

  # 优先使用统一的 Python 资源探测，保持与 raspa-calc 一致
  PY_RES_JSON=""
  echo "$(ts) - INFO - 获取集群资源..."
  PY_RES_JSON=$(fetch_cluster_info_json)
  if [ -n "$PY_RES_JSON" ] && echo "$PY_RES_JSON" | grep -q '"available"'; then
    PY_OK=$(python - "$PY_RES_JSON" <<'PY' 2>/dev/null || true
import json,sys
try:
  d=json.loads(sys.stdin.read())
  if not d.get('available'): raise SystemExit(1)
  print(d.get('total_cpus',0), d.get('allocated_cpus',0), d.get('available_cpus',0))
  for n in d.get('nodes') or []:
    nm=n.get('node')
    tot=n.get('total_cpus',0)
    alloc=n.get('allocated_cpus',0)
    topo=n.get('topology') or '?'
    load=n.get('load')
    free=n.get('free_cpus',0)
    print(f"NODE::{nm}::{tot}::{alloc}::{topo}::{load if load is not None else '未知'}::{free}")
except Exception:
  raise SystemExit(1)
PY
    )
    if [ -n "$PY_OK" ]; then
      # 解析三元组与节点行
      first_line=$(printf "%s\n" "$PY_OK" | head -n1)
      read -r CL_TOTAL CL_ALLOC CL_IDLE <<< "$first_line"
      while IFS= read -r L; do
        case "$L" in NODE::*)
          IFS='::' read -r _ tag_nm tag_tot tag_alloc tag_topo tag_load tag_free <<< "$L"
          CL_NODE_LINES+=("  ${tag_nm}: 总${tag_tot}线程 (拓扑${tag_topo}), 已分配${tag_alloc}, CPULoad=${tag_load}, 估计可用=${tag_free}")
          tpc_raw="${tag_topo##*:}"
          if [[ "$tpc_raw" =~ ^[0-9]+$ ]] && [ "$tpc_raw" -ge 1 ]; then
            NODE_TPC["$tag_nm"]="$tpc_raw"
          fi
        ;; esac
      done < <(printf "%s\n" "$PY_OK")
      CL_METHOD="python_task_runner"
    fi
  fi

  # 兜底：仍然尝试本地 sinfo（带超时）
  if [ "$CL_METHOD" = "none" ] && command -v sinfo >/dev/null 2>&1; then
    if out=$(timeout 5s sinfo -N -h -o '%N|%c|%C|%O|%z' 2>/dev/null); then
      if [ -n "$out" ]; then
        while IFS='|' read -r nm cCpt Csum load topo; do
          [ -z "$nm" ] && continue
          IFS='/' read -r c_alloc c_idle c_other c_total <<< "$Csum"
          c_alloc=${c_alloc:-0}; c_idle=${c_idle:-0}; c_other=${c_other:-0}; c_total=${c_total:-${cCpt:-0}}
          # 物理容量/分配折算
          free=$(( c_total - c_alloc - c_other ))
          load_disp="$load"; [ -z "$load_disp" ] && load_disp="未知"
          load_clean=${load%"*"}
          case "${load_clean,,}" in
            ""|"unknown"|"(null)"|"n/a"|"-") load_int=0 ;;
            *) load_int=$(printf "%.0f" "$load_clean" 2>/dev/null || printf "0") ;;
          esac
          capacity=$c_total
          alloc_eff=$c_alloc
          load_eff=$load_int
          free=$(( capacity - alloc_eff - c_other ))
          by_load=$(( capacity - load_eff ))
          [ "$by_load" -lt "$free" ] && free=$by_load
          [ "$free" -lt 0 ] && free=0
          CL_TOTAL=$((CL_TOTAL + capacity))
          CL_ALLOC=$((CL_ALLOC + alloc_eff))
          CL_OTHER=$((CL_OTHER + c_other))
          CL_IDLE=$((CL_IDLE + free))
          CL_NODE_LINES+=("  ${nm}: 总${capacity}核 (拓扑${topo:-?}), 已分配${alloc_eff}, CPULoad=${load_disp}, 估计可用=${free}")
          tpc_raw="${topo##*:}"
          if [[ "$tpc_raw" =~ ^[0-9]+$ ]] && [ "$tpc_raw" -ge 1 ]; then
            NODE_TPC["$nm"]="$tpc_raw"
          fi
        done <<< "$out"
        CL_METHOD="sinfo_per_node"
      fi
    fi
    if [ "$CL_METHOD" = "none" ]; then
      if out=$(timeout 3s sinfo -h -o '%C' 2>/dev/null); then
        IFS='/' read -r c_alloc c_idle c_other c_total <<< "${out%%$'\n'*}"
        CL_ALLOC=${c_alloc:-0}; idle=${c_idle:-0}; CL_OTHER=${c_other:-0}; CL_TOTAL=${c_total:-0}; CL_IDLE=${idle:-0}
        CL_METHOD="sinfo_summary"
      fi
    fi
  fi

  echo "$(ts) - INFO - === 步骤3：设置计算参数 ==="
  echo "$(ts) - INFO - 当前节点CPU核心数: $(node_cpu_count)"
  if [ "$CL_METHOD" != "none" ]; then
    echo "$(ts) - INFO - 集群总 CPU核心数: ${CL_TOTAL}"
    echo "$(ts) - INFO - 集群已分配 CPU核心数: ${CL_ALLOC}"
    echo "$(ts) - INFO - 集群当前可用 CPU核心数: ${CL_IDLE}"
    if [ "$CL_METHOD" = "sinfo_per_node" ] && [ ${#CL_NODE_LINES[@]} -gt 0 ]; then
      echo "$(ts) - INFO - 节点资源详情（线程总数/负载/建议可用线程）："
      for line in "${CL_NODE_LINES[@]}"; do
        echo "$(ts) - INFO - ${line}"
      done
    fi
  else
    echo "$(ts) - INFO - 未检测到可用集群统计，使用当前节点信息"
  fi

  echo "$(ts) - INFO - 可用任务数: ${USEFUL_TASKS} (运行中=${RUNNING_COUNT}, 待处理=${PENDING_COUNT})"
  RECOMMEND_MODE_RAW="${RASPA_SCALE_RECOMMEND:-}"
  RECOMMEND_MODE="$(printf "%s" "${RECOMMEND_MODE_RAW}" | tr '[:upper:]' '[:lower:]')"
  if [ -z "$RECOMMEND_MODE" ] || [ "$RECOMMEND_MODE" = "auto" ]; then
    RECOMMEND_MODE="run_idle"
  fi
  case "$RECOMMEND_MODE" in
    run_idle|run-idle|running|run|run+idle|running+idle|workdir) RECOMMEND_MODE="run_idle" ;;
    idle|free|available) RECOMMEND_MODE="idle" ;;
    full|total|all|max) RECOMMEND_MODE="full" ;;
    *) RECOMMEND_MODE="run_idle" ;;
  esac

  RECOMMENDED=$USEFUL_TASKS
  RECOMMEND_NOTE="基于任务数量"
  if [ "$CL_METHOD" != "none" ] && [ "$CL_TOTAL" -gt 0 ]; then
    if [ "$RECOMMEND_MODE" = "idle" ]; then
      RECOMMEND_CAP=$CL_IDLE
      RECOMMEND_NOTE="基于集群空闲资源"
      if [ "$CL_TOTAL" -gt 0 ]; then
        RECOMMEND_NOTE="${RECOMMEND_NOTE}，总容量${CL_TOTAL}"
      fi
    elif [ "$RECOMMEND_MODE" = "full" ]; then
      RECOMMEND_CAP=$CL_TOTAL
      RECOMMEND_NOTE="基于集群总容量"
      if [ "$CL_IDLE" -ge 0 ]; then
        RECOMMEND_NOTE="${RECOMMEND_NOTE}，空闲约${CL_IDLE}"
      fi
    else
      RECOMMEND_CAP=$((RUNNING_COUNT + CL_IDLE))
      RECOMMEND_NOTE="基于运行中+集群空闲资源 (运行中${RUNNING_COUNT}, 空闲${CL_IDLE})"
      if [ "$CL_TOTAL" -gt 0 ]; then
        RECOMMEND_NOTE="${RECOMMEND_NOTE}，总容量${CL_TOTAL}"
      fi
    fi
    if [ -n "${RECOMMEND_CAP:-}" ] && [ "$RECOMMENDED" -gt "$RECOMMEND_CAP" ]; then
      RECOMMENDED=$RECOMMEND_CAP
    fi
  fi
  [ "$RECOMMENDED" -lt 0 ] && RECOMMENDED=0
  echo "$(ts) - INFO - 建议使用CPU核心数: ${RECOMMENDED} (${RECOMMEND_NOTE})"
}
