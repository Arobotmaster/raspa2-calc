status_show_help() {
  local cmd_name="${STATUS_CMD_NAME:-raspa-scale status}"
  echo "RASPA高通量计算状态管理工具"
  echo ""
  echo "用法: ${cmd_name} [选项] [子目录]"
  echo ""
  echo "选项:"
  echo "  -h, --help          显示此帮助信息"
  echo "  -s, --status        显示任务状态统计（默认）"
  echo "  -d, --detail        显示详细任务列表"
  echo "  -r, --reset-failed  将所有__failed任务重置为待处理状态"
  echo "  -c, --reset-completed  将所有__completed任务重置为待处理状态"
  echo "  -a, --reset-all     重置所有非__done状态的任务"
  echo "  -l, --logs          显示最新的日志文件"
  echo "  -m, --monitor       实时监控任务进度"
  echo ""
  echo "参数:"
  echo "  子目录              指定子目录名称（默认'.'，若能唯一识别子目录则自动选择）"
  echo ""
  echo "示例:"
  echo "  ${cmd_name}                    # 显示基本状态"
  echo "  ${cmd_name} -d                 # 显示详细信息"
  echo "  ${cmd_name} -r                 # 重置失败任务"
  echo "  ${cmd_name} -m                 # 实时监控"
  echo "  ${cmd_name} --reset-all 5      # 重置子目录5中的所有任务"
}

status_scan_status_counts() {
  local target="$1"
  local list_file="$target/.raspa_queue/tasks.list"
  local list_mode=0
  if [ -f "$list_file" ]; then
    list_mode=1
  fi
  local cache_sec="${RASPA_STATUS_CACHE_SEC:-5}"
  local now
  if ! [[ "$cache_sec" =~ ^[0-9]+$ ]]; then
    cache_sec=5
  fi
  now=$(date +%s)
  if [ "$STATUS_CACHE_TARGET" = "$target" ] && [ "$STATUS_CACHE_TS" -gt 0 ] && [ "$cache_sec" -gt 0 ]; then
    if [ $((now - STATUS_CACHE_TS)) -le "$cache_sec" ]; then
      STATUS_PENDING="$STATUS_CACHE_PENDING"
      STATUS_RUNNING="$STATUS_CACHE_RUNNING"
      STATUS_DONE="$STATUS_CACHE_DONE"
      STATUS_FAILED="$STATUS_CACHE_FAILED"
      STATUS_COMPLETED="$STATUS_CACHE_COMPLETED"
      return 0
    fi
  fi

  STATUS_PENDING=""
  STATUS_RUNNING=""
  STATUS_DONE=""
  STATUS_FAILED=""
  STATUS_COMPLETED=""

  local RASPA_SCALE_SCAN_MODE="fast"
  local RASPA_SCALE_SCAN_PATTERN="^mc"
  scan_task_counts "$target"
  if [[ "${PENDING_COUNT:-}" =~ ^[0-9]+$ ]] && [[ "${RUNNING_COUNT:-}" =~ ^[0-9]+$ ]]; then
    STATUS_PENDING="$PENDING_COUNT"
    STATUS_RUNNING="$RUNNING_COUNT"
  fi
  if [ "$list_mode" -eq 1 ]; then
    scan_task_counts "$target"
    if [[ "${PENDING_COUNT:-}" =~ ^[0-9]+$ ]] && [[ "${RUNNING_COUNT:-}" =~ ^[0-9]+$ ]]; then
      STATUS_PENDING="$PENDING_COUNT"
      STATUS_RUNNING="$RUNNING_COUNT"
    fi
  fi

  local out
  out=$(python - "$target" <<'PY' 2>/dev/null || true
import os
import re
import sys

target = sys.argv[1] if len(sys.argv) > 1 else ""
if not target:
    sys.exit(1)

done = failed = completed = 0
pat = re.compile(r"^mc")
list_file = os.path.join(target, ".raspa_queue", "tasks.list")

def count_status(name: str) -> str:
    if name.endswith("__done"):
        return "done"
    if name.endswith("__failed"):
        return "failed"
    if name.endswith("__completed"):
        return "completed"
    return ""

if os.path.isfile(list_file):
    try:
        with open(list_file, "r", encoding="utf-8") as fh:
            tasks = [line.rstrip("\n").strip() for line in fh if line.strip()]
    except Exception:
        tasks = []
    for rel in tasks:
        base = os.path.join(target, rel.rstrip("/"))
        for suffix in ("__done", "__failed", "__completed"):
            if os.path.isdir(base + suffix):
                status = count_status(base + suffix)
                if status == "done":
                    done += 1
                elif status == "failed":
                    failed += 1
                elif status == "completed":
                    completed += 1
                break
    print(f"{done} {failed} {completed}")
    sys.exit(0)

try:
    with os.scandir(target) as it:
        for entry in it:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except Exception:
                continue
            name = entry.name
            if not pat.match(name):
                continue
            if name.endswith("__done"):
                done += 1
            elif name.endswith("__failed"):
                failed += 1
            elif name.endswith("__completed"):
                completed += 1
except Exception:
    sys.exit(1)

print(f"{done} {failed} {completed}")
PY
  )
  if [ -n "$out" ]; then
    read -r STATUS_DONE STATUS_FAILED STATUS_COMPLETED <<< "$out"
  fi

  if ! [[ "${STATUS_PENDING:-}" =~ ^[0-9]+$ ]]; then
    if [ "$list_mode" -eq 1 ]; then
      STATUS_PENDING=0
    else
      STATUS_PENDING=$(find "$target" -maxdepth 1 -type d -name "mc*" ! -name "*__*" 2>/dev/null | wc -l)
    fi
  fi
  if ! [[ "${STATUS_RUNNING:-}" =~ ^[0-9]+$ ]]; then
    if [ "$list_mode" -eq 1 ]; then
      STATUS_RUNNING=0
    else
      STATUS_RUNNING=$(find "$target" -maxdepth 1 -type d -name "mc*__running" 2>/dev/null | wc -l)
    fi
  fi
  if ! [[ "${STATUS_DONE:-}" =~ ^[0-9]+$ ]]; then
    if [ "$list_mode" -eq 1 ]; then
      STATUS_DONE=0
    else
      STATUS_DONE=$(find "$target" -maxdepth 1 -type d -name "mc*__done" 2>/dev/null | wc -l)
    fi
  fi
  if ! [[ "${STATUS_FAILED:-}" =~ ^[0-9]+$ ]]; then
    if [ "$list_mode" -eq 1 ]; then
      STATUS_FAILED=0
    else
      STATUS_FAILED=$(find "$target" -maxdepth 1 -type d -name "mc*__failed" 2>/dev/null | wc -l)
    fi
  fi
  if ! [[ "${STATUS_COMPLETED:-}" =~ ^[0-9]+$ ]]; then
    if [ "$list_mode" -eq 1 ]; then
      STATUS_COMPLETED=0
    else
      STATUS_COMPLETED=$(find "$target" -maxdepth 1 -type d -name "mc*__completed" 2>/dev/null | wc -l)
    fi
  fi

  STATUS_CACHE_TARGET="$target"
  STATUS_CACHE_TS="$now"
  STATUS_CACHE_PENDING="$STATUS_PENDING"
  STATUS_CACHE_RUNNING="$STATUS_RUNNING"
  STATUS_CACHE_DONE="$STATUS_DONE"
  STATUS_CACHE_FAILED="$STATUS_FAILED"
  STATUS_CACHE_COMPLETED="$STATUS_COMPLETED"
}

status_scan_lists() {
  local target="$1"
  local list_file="$target/.raspa_queue/tasks.list"
  local list_mode=0
  if [ -f "$list_file" ]; then
    list_mode=1
  fi
  local failed_limit="${RASPA_STATUS_DETAIL_LIMIT:-10}"
  local completed_limit="${RASPA_STATUS_DETAIL_LIMIT:-10}"
  local running_limit="${RASPA_STATUS_RUNNING_LIMIT:-0}"
  python - "$target" "$failed_limit" "$completed_limit" "$running_limit" "$list_mode" <<'PY'
import os
import re
import sys

target = sys.argv[1] if len(sys.argv) > 1 else ""
failed_limit = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 10
completed_limit = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 10
running_limit = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].isdigit() else 0
list_mode = sys.argv[5] == "1" if len(sys.argv) > 5 else False

running = []
failed = []
completed = []
pat = re.compile(r"^mc")
list_file = os.path.join(target, ".raspa_queue", "tasks.list")

def sort_key(name):
    m = re.match(r"^mc(\d+)", name)
    if m:
        return (0, int(m.group(1)), name)
    return (1, name)

if list_mode and os.path.isfile(list_file):
    try:
        with open(list_file, "r", encoding="utf-8") as fh:
            tasks = [line.rstrip("\n").strip() for line in fh if line.strip()]
    except Exception:
        tasks = []

    for rel in tasks:
        base = os.path.join(target, rel.rstrip("/"))
        if os.path.isdir(base + "__running"):
            running.append(rel + "__running")
        elif os.path.isdir(base + "__failed"):
            failed.append(rel + "__failed")
        elif os.path.isdir(base + "__completed"):
            completed.append(rel + "__completed")

    running = sorted(running)
    failed = sorted(failed)[:failed_limit]
    completed = sorted(completed)[:completed_limit]
    if running_limit > 0:
        running = running[:running_limit]

    print("RUNNING")
    for name in running:
        print(name)
    print("FAILED")
    for name in failed:
        print(name)
    print("COMPLETED")
    for name in completed:
        print(name)
    sys.exit(0)

try:
    with os.scandir(target) as it:
        for entry in it:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except Exception:
                continue
            name = entry.name
            if not pat.match(name):
                continue
            if name.endswith("__running"):
                running.append(name)
            elif name.endswith("__failed"):
                failed.append(name)
            elif name.endswith("__completed"):
                completed.append(name)
except Exception:
    pass

running = sorted(running, key=sort_key)
failed = sorted(failed, key=sort_key)[:failed_limit]
completed = sorted(completed, key=sort_key)[:completed_limit]
if running_limit > 0:
    running = running[:running_limit]

print("RUNNING")
for name in running:
    print(name)
print("FAILED")
for name in failed:
    print(name)
print("COMPLETED")
for name in completed:
    print(name)
PY
}

status_show_status() {
  echo -e "${BLUE}RASPA任务状态统计${NC}"
  echo "工作目录: ${WORK_DIR}"
  echo "子目录: ${SUBDIR}"
  local target_basename
  target_basename=$(basename "$TARGET_DIR")
  if [[ "$SUBDIR" != "$TARGET_DIR" && "$SUBDIR" != "$target_basename" ]]; then
    echo "目标路径: ${TARGET_DIR}"
  fi
  echo "时间: $(date)"
  echo ""

  if [ ! -d "$TARGET_DIR" ]; then
    echo -e "${RED}目标目录不存在: ${TARGET_DIR}${NC}"
    return
  fi

  status_scan_status_counts "$TARGET_DIR"
  local pending=$STATUS_PENDING
  local running=$STATUS_RUNNING
  local done=$STATUS_DONE
  local failed=$STATUS_FAILED
  local completed=$STATUS_COMPLETED

  local total=$((pending + running + done + failed + completed))

  printf "%-15s %s\n" "状态" "数量"
  echo "------------------------"
  printf "%-15s ${GREEN}%d${NC}\n" "已完成(__done)" $done
  printf "%-15s ${YELLOW}%d${NC}\n" "运行中(__running)" $running
  printf "%-15s ${BLUE}%d${NC}\n" "待处理" $pending
  printf "%-15s ${RED}%d${NC}\n" "失败(__failed)" $failed
  printf "%-15s ${YELLOW}%d${NC}\n" "异常完成(__completed)" $completed
  echo "------------------------"
  printf "%-15s %d\n" "总计" $total

  if [ $total -gt 0 ]; then
    local progress=$((done * 100 / total))
    echo ""
    echo "完成进度: ${progress}% (${done}/${total})"

    # 显示进度条
    local bar_length=50
    local filled_length=$((progress * bar_length / 100))
    printf "进度条: ["
    for i in $(seq 1 $filled_length); do printf "="; done
    printf ">"
    for i in $(seq $((filled_length + 1)) $bar_length); do printf " "; done
    printf "]\n"
  fi
}

status_show_detail() {
  echo -e "${BLUE}详细任务列表${NC}"
  echo ""

  if [ ! -d "$TARGET_DIR" ]; then
    echo -e "${RED}目标目录不存在: ${TARGET_DIR}${NC}"
    return
  fi

  local -a running_tasks=()
  local -a failed_tasks=()
  local -a completed_tasks=()
  local section=""
  while IFS= read -r line; do
    case "$line" in
      RUNNING) section="running" ;;
      FAILED) section="failed" ;;
      COMPLETED) section="completed" ;;
      *)
        case "$section" in
          running) running_tasks+=("$line") ;;
          failed) failed_tasks+=("$line") ;;
          completed) completed_tasks+=("$line") ;;
        esac
        ;;
    esac
  done < <(status_scan_lists "$TARGET_DIR")

  if [ ${#running_tasks[@]} -gt 0 ]; then
    echo -e "${YELLOW}运行中的任务:${NC}"
    for task_name in "${running_tasks[@]}"; do
      echo "  $task_name"
    done
    echo ""
  fi

  if [ ${#failed_tasks[@]} -gt 0 ]; then
    echo -e "${RED}失败的任务（前10个）:${NC}"
    for task_name in "${failed_tasks[@]}"; do
      echo "  $task_name"
    done
    echo ""
  fi

  if [ ${#completed_tasks[@]} -gt 0 ]; then
    echo -e "${YELLOW}异常完成的任务（前10个）:${NC}"
    for task_name in "${completed_tasks[@]}"; do
      echo "  $task_name"
    done
    echo ""
  fi
}

status_reset_tasks() {
  local status_suffix="$1"
  local action_desc="$2"
  local list_file="$TARGET_DIR/.raspa_queue/tasks.list"
  local list_mode=0
  if [ -f "$list_file" ]; then
    list_mode=1
  fi

  if [ ! -d "$TARGET_DIR" ]; then
    echo -e "${RED}目标目录不存在: ${TARGET_DIR}${NC}"
    return
  fi

  local tasks=()
  if [ "$list_mode" -eq 1 ]; then
    while IFS= read -r rel; do
      [ -z "$rel" ] && continue
      local base="$TARGET_DIR/${rel%/}"
      if [ -d "${base}${status_suffix}" ]; then
        tasks+=("${base}${status_suffix}")
      fi
    done < "$list_file"
  else
    tasks=($(find "$TARGET_DIR" -type d -name "mc*${status_suffix}" | sort -V))
  fi

  if [ ${#tasks[@]} -eq 0 ]; then
    echo "没有找到${action_desc}任务。"
    return
  fi

  echo "找到 ${#tasks[@]} 个${action_desc}任务。"
  echo -n "确定要重置这些任务吗？[y/N]: "
  read -r response

  if [[ "$response" =~ ^[Yy]$ ]]; then
    local reset_count=0
    for task in "${tasks[@]}"; do
      local task_name
      task_name=$(basename "$task")
      local base_name=${task_name%${status_suffix}}
      local new_path
      if [ "$list_mode" -eq 1 ]; then
        new_path="${task%${status_suffix}}"
      else
        new_path="${TARGET_DIR}/${base_name}"
      fi

      if [ ! -e "$new_path" ]; then
        mv "$task" "$new_path"
        ((reset_count++))
        if [ "$list_mode" -eq 1 ]; then
          echo "重置: $(basename "$task") -> $(basename "$new_path")"
        else
          echo "重置: $task_name -> $base_name"
        fi
      else
        echo "跳过: $task_name (目标目录已存在)"
      fi
    done
    echo "成功重置了 $reset_count 个任务。"
  else
    echo "操作已取消。"
  fi
}

status_show_logs() {
  echo -e "${BLUE}最新日志文件${NC}"
  echo ""

  # 查找日志文件
  local log_files=($(find "${WORK_DIR}" -name "log__*_job_output*" -o -name "core_*.log" -o -name "slurm_output_*.out" -o -name "pbs_output_*.out" | sort -t))

  if [ ${#log_files[@]} -eq 0 ]; then
    echo "未找到日志文件。"
    return
  fi

  echo "可用的日志文件:"
  for i in "${!log_files[@]}"; do
    local file="${log_files[$i]}"
    local size
    size=$(du -h "$file" 2>/dev/null | cut -f1)
    local mtime
    mtime=$(stat -c %y "$file" 2>/dev/null | cut -d' ' -f1,2 | cut -d'.' -f1)
    printf "%2d. %-50s %8s %19s\n" $((i+1)) "$(basename "$file")" "$size" "$mtime"
  done

  echo ""
  echo -n "选择要查看的日志文件编号 [1-${#log_files[@]}], 或按回车退出: "
  read -r choice

  if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#log_files[@]} ]; then
    local selected_file="${log_files[$((choice-1))]}"
    echo ""
    echo -e "${GREEN}查看文件: $selected_file${NC}"
    echo "按 Ctrl+C 退出查看"
    sleep 2
    tail -f "$selected_file"
  fi
}

status_monitor_progress() {
  echo -e "${BLUE}实时监控任务进度${NC}"
  echo "按 Ctrl+C 退出监控"
  echo ""

  while true; do
    clear
    status_show_status
    echo ""
    echo "更新时间: $(date)"
    echo "每30秒自动刷新..."
    sleep 30
  done
}

status_main() {
  STATUS_CMD_NAME="${STATUS_CMD_NAME:-raspa-scale status}"

  WORK_DIR=${RASPA_WORK_DIR:-$PWD}
  SUBDIR="."
  ACTION="status"
  SUBDIR_SET=0
  TARGET_DIR=""

  # 颜色定义
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  NC='\033[0m'

  SCAN_CACHE_TS=0
  SCAN_CACHE_TARGET=""
  SCAN_CACHE_PENDING=0
  SCAN_CACHE_RUNNING=0

  STATUS_CACHE_TS=0
  STATUS_CACHE_TARGET=""
  STATUS_CACHE_PENDING=0
  STATUS_CACHE_RUNNING=0
  STATUS_CACHE_DONE=0
  STATUS_CACHE_FAILED=0
  STATUS_CACHE_COMPLETED=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h|--help)
        ACTION="help"
        shift
        ;;
      -d|--detail)
        ACTION="detail"
        shift
        ;;
      -r|--reset-failed)
        ACTION="reset_failed"
        shift
        ;;
      -c|--reset-completed)
        ACTION="reset_completed"
        shift
        ;;
      -a|--reset-all)
        ACTION="reset_all"
        shift
        ;;
      -l|--logs)
        ACTION="logs"
        shift
        ;;
      -m|--monitor)
        ACTION="monitor"
        shift
        ;;
      -s|--status)
        ACTION="status"
        shift
        ;;
      --)
        shift
        break
        ;;
      -* )
        echo "未知选项: $1"
        echo "使用 -h 或 --help 查看帮助信息"
        exit 1
        ;;
      *)
        if [ $SUBDIR_SET -eq 1 ]; then
          echo "只支持一个子目录参数，收到额外参数: $1"
          exit 1
        fi
        SUBDIR="$1"
        SUBDIR_SET=1
        shift
        ;;
    esac
  done

  if [[ $# -gt 0 ]]; then
    if [ $SUBDIR_SET -eq 1 ]; then
      echo "只支持一个子目录参数，收到额外参数: $1"
      exit 1
    fi
    SUBDIR="$1"
    SUBDIR_SET=1
    shift
    if [[ $# -gt 0 ]]; then
      echo "只支持一个子目录参数，收到额外参数: $1"
      exit 1
    fi
  fi

  if [[ -z "$SUBDIR" ]]; then
    SUBDIR="."
  fi

  if [[ "$SUBDIR" = /* ]]; then
    TARGET_DIR="${SUBDIR%/}"
    if [[ -z "$TARGET_DIR" ]]; then
      TARGET_DIR="/"
    fi
  else
    # 优先相对于当前目录解析，若不存在再回退到 WORK_DIR
    local CWD
    CWD="$(pwd -P)"
    if [ -d "$CWD/${SUBDIR#/}" ]; then
      TARGET_DIR="$CWD/${SUBDIR#/}"
    else
      TARGET_DIR="${WORK_DIR%/}/${SUBDIR#/}"
    fi
  fi

  if [[ "$TARGET_DIR" != "/" ]]; then
    TARGET_DIR="${TARGET_DIR%/}"
  fi

  # 自动检测：当用户未显式指定子目录且当前目录/工作目录下只有一个包含 mc* 的子目录时，自动选择它
  if [[ $SUBDIR_SET -eq 0 ]]; then
    # 只在当前选择为 '.' 时尝试
    if [[ "$SUBDIR" = "." ]]; then
      local candidate
      candidate=$(python - "$TARGET_DIR" <<'PY' 2>/dev/null || true
import os
import sys

base = sys.argv[1] if len(sys.argv) > 1 else ""
if not base:
    sys.exit(0)

def has_mc_dir(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False) and entry.name.startswith("mc"):
                        return True
                except Exception:
                    continue
    except Exception:
        return False
    return False

def has_task_list(path: str) -> bool:
    list_path = os.path.join(path, ".raspa_queue", "tasks.list")
    if not os.path.isfile(list_path):
        return False
    try:
        with open(list_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    return True
    except Exception:
        return False
    return False

candidates = []
try:
    with os.scandir(base) as it:
        for entry in it:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except Exception:
                continue
            name = entry.name
            if name.startswith("."):
                continue
            if has_task_list(entry.path) or has_mc_dir(entry.path):
                candidates.append(entry.path)
except Exception:
    pass

if len(candidates) == 1:
    print(candidates[0])
PY
      )
      if [[ -n "$candidate" ]]; then
        TARGET_DIR="$candidate"
        SUBDIR="$(basename "$TARGET_DIR")"
      fi
    fi
  fi

  case "$ACTION" in
    help)
      status_show_help
      ;;
    detail)
      status_show_status
      echo ""
      status_show_detail
      ;;
    reset_failed)
      status_reset_tasks "__failed" "失败"
      ;;
    reset_completed)
      status_reset_tasks "__completed" "异常完成"
      ;;
    reset_all)
      echo "重置所有非完成状态的任务..."
      status_reset_tasks "__failed" "失败"
      status_reset_tasks "__completed" "异常完成"
      status_reset_tasks "__running" "运行中"
      ;;
    logs)
      status_show_logs
      ;;
    monitor)
      status_monitor_progress
      ;;
    status)
      status_show_status
      ;;
  esac
}

handle_status_command() {
  local cmd="${1:-}"
  if [ "$cmd" != "status" ] && [ "$cmd" != "--status" ]; then
    return 1
  fi
  shift || true
  status_main "$@"
  return 0
}
