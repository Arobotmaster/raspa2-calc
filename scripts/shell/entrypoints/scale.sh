#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../lib/scale"
COMMON_LIB_DIR="$SCRIPT_DIR/../lib"
# shellcheck source=/dev/null
source "$LIB_DIR/usage.sh"
source "$LIB_DIR/kill.sh"
source "$COMMON_LIB_DIR/disk.sh"
source "$LIB_DIR/scan.sh"
source "$LIB_DIR/config.sh"
source "$LIB_DIR/target.sh"
source "$LIB_DIR/cluster.sh"
source "$LIB_DIR/plan.sh"
source "$LIB_DIR/slurm.sh"
source "$LIB_DIR/status.sh"

: "${USER:=}"
: "${RASPA_WORK_DIR:=}"
: "${RASPA_SUBDIR:=}"
: "${RASPA_OUTPUT_DIR:=}"
: "${RASPA_NODE_PLAN:=}"
: "${RASPA_NODE_PRIORITIES:=}"
: "${RASPA_ALLOWED_NODES:=}"

if [ $# -ge 1 ] && { [ "$1" = "-h" ] || [ "$1" = "--help" ]; }; then
  usage_short
  exit 0
fi

if handle_status_command "$@"; then
  exit 0
fi
if handle_kill_command "$@"; then
  exit 0
fi

INTERACTIVE=0
ACCEPT_AUTO=0
APPLY_ACTIONS=0
LIMIT_ONLY=0
RAW_LIMIT=""
RAW_SUBDIR=""
POSITIONAL=()

while [ $# -ge 1 ]; do
  case "${1:-}" in
    -i|--interactive|interactive|ask)
      INTERACTIVE=1; shift || true ;;
    -h|--help)
      usage; exit 0 ;;
    -y|--accept)
      ACCEPT_AUTO=1; shift || true ;;
    -a|--apply|--autoscale)
      APPLY_ACTIONS=1; shift || true ;;
    --limit-only)
      LIMIT_ONLY=1; shift || true ;;
    --)
      shift || true
      while [ $# -ge 1 ]; do
        POSITIONAL+=("$1")
        shift || true
      done
      ;;
    *)
      POSITIONAL+=("$1")
      shift || true ;;
  esac
done

if [ ${#POSITIONAL[@]} -ge 1 ]; then
  if [[ "${POSITIONAL[0]}" =~ ^[0-9]+$ ]]; then
    RAW_LIMIT="${POSITIONAL[0]}"
    POSITIONAL=("${POSITIONAL[@]:1}")
  fi
fi

RAW_SUBDIR="${POSITIONAL[0]:-""}"

ABS_PWD="$(pwd -P)"

# 尝试从配置读取节点优先级，供后续重排/生成计划（支持无 PyYAML 场景的简易解析）
load_node_priorities
if [ -n "${RASPA_ALLOWED_NODES:-}" ]; then
  echo "限制节点白名单: ${RASPA_ALLOWED_NODES}"
fi

prepare_target_dir

LIMIT_FILE="$TARGET_DIR/.raspa_worker_limit"

# 在设置并发前输出资源与可用任务概览；若交互或未提供数值，则提示输入
SCAN_CACHE_TS=0
SCAN_CACHE_TARGET=""
SCAN_CACHE_RUNNING=0
SCAN_CACHE_PENDING=0

scan_task_counts "$TARGET_DIR"

declare -a CL_NODE_LINES=()
declare -A NODE_TPC=()

collect_cluster_info

NODE_PLAN_MODE="$RECOMMEND_MODE"
[ "$NODE_PLAN_MODE" = "run_idle" ] && NODE_PLAN_MODE="idle"

CUR_LIMIT=""; [ -f "$LIMIT_FILE" ] && CUR_LIMIT=$(awk 'NR==1{print $1}' "$LIMIT_FILE" 2>/dev/null || true)
NON_TTY=1; [ -t 0 ] && NON_TTY=0

# TTY 且未显式给出并发上限时，默认进入交互模式
if [ "$INTERACTIVE" -eq 0 ] && [ "$NON_TTY" -eq 0 ] && [ -z "$RAW_LIMIT" ] && [ "$ACCEPT_AUTO" -eq 0 ]; then
  INTERACTIVE=1
fi

PRESET_ACTION_MODE=""
SKIP_LIMIT_PROMPT=0
if [ "$INTERACTIVE" -eq 1 ] && [ -z "$RAW_LIMIT" ] && [ "$APPLY_ACTIONS" -eq 0 ] && [ "$LIMIT_ONLY" -eq 0 ] && [ "$ACCEPT_AUTO" -eq 0 ]; then
  echo
  echo "请选择模式："
  echo "  [1] 自动扩缩容（写入并执行）"
  echo "  [2] 终止任务（按用户/范围/列表）"
  echo "  [3] 查看任务状态（raspa-status）"
  echo "  [q] 退出"
  read -r -p "请输入选择 [1/2/3/q]: " mode_choice || mode_choice=""
  case "${mode_choice,,}" in
    1)
      APPLY_ACTIONS=1
      PRESET_ACTION_MODE="apply"
      ;;
    2|k|kill)
      kill_interactive_menu
      exit 0
      ;;
    3|s|status)
      if [ -n "$RAW_SUBDIR" ]; then
        status_main "$RAW_SUBDIR"
      else
        status_main
      fi
      exit 0
      ;;
    q|quit|exit|"")
      echo "操作已取消"
      exit 0
      ;;
    *)
      echo "无效选择"
      exit 1
      ;;
  esac
fi

if [ -n "$RAW_LIMIT" ]; then
  NEW_LIMIT="$RAW_LIMIT"
else
  # 无显式数值时，依据交互/TTY/接受策略自动选择
  if [ "$USEFUL_TASKS" -eq 0 ]; then
    echo "$(ts) - INFO - 可用任务数为0：不建议提高并发，保持当前上限${CUR_LIMIT:+=$CUR_LIMIT}"
  fi
  if [ "$SKIP_LIMIT_PROMPT" -eq 1 ]; then
    NEW_LIMIT=${CUR_LIMIT:-$RECOMMENDED}
    [ -z "$NEW_LIMIT" ] && NEW_LIMIT=1
  elif [ "$INTERACTIVE" -eq 1 ]; then
    if [ "$USEFUL_TASKS" -eq 0 ]; then
      prompt="请输入并发上限 (>=0) [建议:${RECOMMENDED}${CUR_LIMIT:+, 当前:${CUR_LIMIT}}]: "
    else
      prompt="请输入并发上限 (0-${USEFUL_TASKS}) [建议:${RECOMMENDED}${CUR_LIMIT:+, 当前:${CUR_LIMIT}}]: "
    fi
    read -r -p "$prompt" input_limit || input_limit=""
    if [ -z "$input_limit" ]; then
      NEW_LIMIT=${RECOMMENDED:-1}
    else
      NEW_LIMIT="$input_limit"
    fi
  else
    if [ "$ACCEPT_AUTO" -eq 1 ] || [ "$NON_TTY" -eq 1 ]; then
      NEW_LIMIT=${RECOMMENDED:-1}
      echo "$(ts) - INFO - 自动采用建议并发: $NEW_LIMIT"
    else
      NEW_LIMIT=${RECOMMENDED:-1}
      echo "$(ts) - INFO - 采用建议并发: $NEW_LIMIT（使用 -i 可交互输入，或 -y 自动接受）"
    fi
  fi
fi

if ! [[ "$NEW_LIMIT" =~ ^[0-9]+$ ]] || [ "${NEW_LIMIT}" -lt 0 ]; then
  echo "错误: 并发上限必须为非负整数 (得到: '${NEW_LIMIT}')" >&2
  exit 1
fi

ACTION_MODE="dry"
if [ -n "$PRESET_ACTION_MODE" ]; then
  ACTION_MODE="$PRESET_ACTION_MODE"
elif [ "$APPLY_ACTIONS" -eq 1 ]; then
  ACTION_MODE="apply"
elif [ "$LIMIT_ONLY" -eq 1 ]; then
  ACTION_MODE="limit"
# -y/--accept 视为“无需交互直接执行”，默认走自动扩缩容
elif [ "$ACCEPT_AUTO" -eq 1 ]; then
  ACTION_MODE="apply"
elif [ "$NON_TTY" -eq 0 ]; then
  echo
  echo "请选择操作（默认仅查看，不改动任何作业）："
  echo "  [d] 仅查看/不修改"
  echo "  [l] 写入并发上限，不提交/取消作业"
  echo "  [a] 写入并发上限并自动扩/缩容"
  read -r -p "请输入选择 [d/l/a] (默认d): " mode_choice || mode_choice=""
  case "${mode_choice,,}" in
    l) ACTION_MODE="limit" ;;
    a) ACTION_MODE="apply" ;;
    *) ACTION_MODE="dry" ;;
  esac
fi

if [ "$ACTION_MODE" = "dry" ]; then
  echo "安全模式：未指定 --apply/--limit-only，保持只读，不修改并发或作业。"
  exit 0
fi

echo "$NEW_LIMIT" > "$LIMIT_FILE"
echo "已设置 .raspa_worker_limit = $NEW_LIMIT ($TARGET_DIR)"

DO_AUTOSCALE=0
if [ "$ACTION_MODE" = "apply" ]; then
  DO_AUTOSCALE=1
fi

PLAN_FILE="$TARGET_DIR/.raspa_node_plan"
NODE_PLAN="${RASPA_NODE_PLAN:-}"
PLAN_REBUILT_ATTEMPTED=0
# 若用户未显式指定 NODE_PLAN，优先刷新集群信息并基于最新负载生成计划
if [ "$DO_AUTOSCALE" -eq 1 ]; then
  PY_RES_JSON=$(fetch_cluster_info_json)
fi
if [ "$DO_AUTOSCALE" -eq 1 ] && [ -z "$NODE_PLAN" ] && [ -n "$PY_RES_JSON" ]; then
  PLAN_REBUILT_ATTEMPTED=1
  PLAN_REBUILT=$(build_node_plan "$NEW_LIMIT" "$RASPA_NODE_PRIORITIES" "$PY_RES_JSON" "$NODE_PLAN_MODE")
  if [ -n "$PLAN_REBUILT" ]; then
    NODE_PLAN="$PLAN_REBUILT"
    echo "$NODE_PLAN" > "$PLAN_FILE"
    echo "$(ts) - INFO - 重建节点分配计划: $NODE_PLAN (用于节点倾向分配，不代表本次新增数量)"
  elif [ -n "${RASPA_ALLOWED_NODES:-}" ]; then
    rm -f "$PLAN_FILE" 2>/dev/null || true
    echo "$(ts) - INFO - 限定节点(${RASPA_ALLOWED_NODES}) 当前无可用资源，未生成新的节点分配计划。"
  fi
fi
if [ -z "$NODE_PLAN" ] && [ -f "$PLAN_FILE" ] && ! { [ "$PLAN_REBUILT_ATTEMPTED" -eq 1 ] && [ -n "${RASPA_ALLOWED_NODES:-}" ]; }; then
  NODE_PLAN="$(tr -d ' \t\r\n' < "$PLAN_FILE")"
fi

if [ "${DO_AUTOSCALE:-0}" -ne 1 ]; then
  echo "提示：未启用自动扩缩容 (--apply)。仅写入了并发上限${NODE_PLAN:+/节点计划}，未提交或取消任何作业。"
  exit 0
fi

# 依据集群类型执行自动扩缩容
if command -v sbatch >/dev/null 2>&1 && command -v squeue >/dev/null 2>&1; then
  slurm_autoscale
elif command -v qsub >/dev/null 2>&1 && command -v qstat >/dev/null 2>&1; then
  # =========================
  # PBS: 自动扩缩容（安全过滤）
  # =========================
  echo "检测到PBS调度器，当前版本暂未实现自动扩缩容逻辑，仅更新并发上限文件。"
  : # 占位，避免空then块导致语法错误
else
  echo "$(ts) - INFO - 未检测到 SLURM/PBS 调度器，仅更新并发上限"
fi

echo "并发调整完成"
