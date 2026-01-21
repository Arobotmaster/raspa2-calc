kill_require_scancel() {
  if ! command -v scancel >/dev/null 2>&1; then
    echo "错误: 未检测到 scancel，无法终止任务（需要 SLURM 环境）" >&2
    exit 1
  fi
}

kill_require_squeue() {
  if ! command -v squeue >/dev/null 2>&1; then
    echo "错误: 未检测到 squeue，无法按节点筛选任务（需要 SLURM 环境）" >&2
    exit 1
  fi
}

kill_confirm() {
  local prompt="$1"
  if [ "${KILL_FORCE:-0}" -eq 1 ]; then
    return 0
  fi
  read -r -p "$prompt [y/N]: " confirm
  [[ $confirm =~ ^[Yy]$ ]]
}

kill_user_jobs() {
  local username="$1"
  [ -z "$username" ] && echo "错误: 用户名不能为空" >&2 && exit 1
  kill_require_scancel
  echo "正在获取用户 $username 的所有任务..."
  local job_ids
  job_ids=$(squeue -u "$username" -h -o "%i" 2>/dev/null || true)
  if [ -z "$job_ids" ]; then
    echo "用户 $username 没有正在运行或排队的任务"
    return 0
  fi
  echo "找到以下任务ID:"
  echo "$job_ids"
  echo ""
  if kill_confirm "确认删除用户 $username 的所有任务?"; then
    echo "正在删除任务..."
    for job_id in $job_ids; do
      echo "删除任务 $job_id"
      scancel "$job_id"
    done
    echo "完成删除用户 $username 的所有任务"
  else
    echo "操作已取消"
  fi
}

kill_range_jobs() {
  local range="$1"
  local start
  local end
  start=$(echo "$range" | cut -d'-' -f1)
  end=$(echo "$range" | cut -d'-' -f2)
  if [[ ! $start =~ ^[0-9]+$ ]] || [[ ! $end =~ ^[0-9]+$ ]]; then
    echo "错误: 范围格式不正确，应为 开始-结束 (例如: 12894-13421)" >&2
    exit 1
  fi
  kill_require_scancel
  if ! kill_confirm "确认删除作业ID从 $start 到 $end 的任务?"; then
    echo "操作已取消"
    return 0
  fi
  echo "正在删除作业ID从 $start 到 $end 的任务..."
  for i in $(seq "$start" "$end"); do
    echo "删除任务 $i"
    scancel "$i"
  done
  echo "完成删除范围任务"
}

kill_list_jobs() {
  local job_list="$1"
  [ -z "$job_list" ] && echo "错误: 作业ID列表不能为空" >&2 && exit 1
  kill_require_scancel
  if ! kill_confirm "确认删除指定的任务列表?"; then
    echo "操作已取消"
    return 0
  fi
  echo "正在删除指定的任务列表..."
  IFS=',' read -r -a job_array <<< "$job_list"
  for job_id in "${job_array[@]}"; do
    job_id=$(echo "$job_id" | tr -d ' ')
    if [[ $job_id =~ ^[0-9]+$ ]]; then
      echo "删除任务 $job_id"
      scancel "$job_id"
    else
      echo "警告: 跳过无效的作业ID '$job_id'"
    fi
  done
  echo "完成删除列表任务"
}

resolve_kill_target_dir() {
  local abs_pwd base_dir subdir target_dir has_tasks
  abs_pwd="$(pwd -P)"
  has_work_marker() {
    local dir="$1"
    if [ -d "$dir/job_templates" ]; then
      return 0
    fi
    if [ -d "$dir/.raspa_queue" ] || [ -f "$dir/.raspa_worker_limit" ] || [ -f "$dir/.raspa_config.yaml" ]; then
      return 0
    fi
    local has_tasks
    has_tasks=$(find "$dir" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -print -quit 2>/dev/null)
    [ -n "$has_tasks" ]
  }

  if [ -n "${RASPA_WORK_DIR:-}" ] && [ -d "$RASPA_WORK_DIR" ]; then
    base_dir="$(cd "$RASPA_WORK_DIR" && pwd -P)"
  else
    base_dir="$abs_pwd"
    while [ "$base_dir" != "/" ] && ! has_work_marker "$base_dir"; do
      base_dir="$(dirname "$base_dir")"
    done
    if ! has_work_marker "$base_dir"; then
      echo "$abs_pwd"
      return
    fi
  fi
  if [ "$abs_pwd" = "$base_dir" ]; then
    subdir="."
  else
    subdir="${abs_pwd#$base_dir/}"
  fi
  if [ "$subdir" = "." ]; then
    target_dir="$base_dir"
  else
    target_dir="$base_dir/$subdir"
  fi
  if [ "$subdir" = "." ]; then
    has_tasks=$(find "$target_dir" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -print -quit 2>/dev/null)
    if [ -z "$has_tasks" ]; then
      local -a candidates=()
      mapfile -t candidates < <(find "$target_dir" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | while read -r d; do
        find "$d" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -print -quit 2>/dev/null | grep -q . && basename "$d"
      done)
      if [ ${#candidates[@]} -eq 1 ]; then
        target_dir="$base_dir/${candidates[0]}"
      fi
    fi
  fi
  if [ -n "$target_dir" ] && [ -d "$target_dir" ]; then
    target_dir="$(cd "$target_dir" && pwd -P)"
  fi
  echo "$target_dir"
}

kill_node_jobs() {
  local node_spec="$1"
  local count_default="$2"
  local username="${3:-}"
  local target_dir="${4:-}"
  [ -z "$username" ] && username="$USER"
  [ -z "$node_spec" ] && echo "错误: 节点列表不能为空" >&2 && exit 1
  kill_require_scancel
  kill_require_squeue

  local -a nodes=()
  local -a counts=()
  IFS=',' read -r -a parts <<< "$node_spec"
  for part in "${parts[@]}"; do
    part="${part//[[:space:]]/}"
    [ -z "$part" ] && continue
    local node="" count=""
    if [[ "$part" == *:* ]]; then
      node="${part%%:*}"
      count="${part#*:}"
    elif [[ "$part" == *=* ]]; then
      node="${part%%=*}"
      count="${part#*=}"
    else
      node="$part"
      count="$count_default"
    fi
    if [ -z "$node" ]; then
      continue
    fi
    if [ -z "$count" ]; then
      echo "错误: 节点 $node 未指定数量（可用 -c 或 node:count）" >&2
      exit 1
    fi
    if ! [[ "$count" =~ ^[0-9]+$ ]]; then
      echo "错误: 节点 $node 数量无效: $count" >&2
      exit 1
    fi
    if [ "$count" -le 0 ]; then
      echo "提示: 节点 $node 数量为0，跳过"
      continue
    fi
    nodes+=("$node")
    counts+=("$count")
  done

  if [ ${#nodes[@]} -eq 0 ]; then
    echo "错误: 未解析到有效节点" >&2
    exit 1
  fi

  if [ -z "$target_dir" ]; then
    target_dir="$(resolve_kill_target_dir)"
  fi
  if [ -z "$target_dir" ]; then
    target_dir="$(pwd -P)"
  fi
  if [ -d "$target_dir" ]; then
    target_dir="$(cd "$target_dir" && pwd -P)"
  fi
  local target_dir_trim="${target_dir%/}"
  local target_prefix="${target_dir_trim}/"
  local jobs_file="$target_dir/.raspa_jobs.list"
  local use_jobs_file=0
  declare -A allowed_jobs=()
  declare -A array_jobs=()
  if [ -s "$jobs_file" ]; then
    while read -r jid name ts extra; do
      [ -n "$jid" ] || continue
      if ! [[ "$jid" =~ ^[0-9]+$ ]]; then
        continue
      fi
      if [ "$extra" = "array" ]; then
        array_jobs["$jid"]=1
      else
        allowed_jobs["$jid"]=1
      fi
    done < "$jobs_file"
    if [ ${#allowed_jobs[@]} -gt 0 ] || [ ${#array_jobs[@]} -gt 0 ]; then
      use_jobs_file=1
    fi
  fi
  if [ "$use_jobs_file" -eq 1 ]; then
    echo "仅终止当前项目记录的作业: $jobs_file"
  else
    echo "仅终止 StdOut/WorkDir 位于 $target_dir 的作业"
  fi
  echo "正在获取用户 $username 在指定节点上的运行中任务..."
  local -a kill_ids=()
  local -a kill_info=()
  declare -A kill_seen=()
  local i
  for i in "${!nodes[@]}"; do
    local node="${nodes[$i]}"
    local count="${counts[$i]}"
    local -a node_jobs=()
    while IFS='|' read -r jid stdout workdir; do
      [[ "$jid" =~ ^[0-9]+(_[0-9]+)?$ ]] || continue
      if [ "$use_jobs_file" -eq 1 ]; then
        local base_jid="${jid%%_*}"
        if [ -n "${allowed_jobs[$jid]+x}" ] || [ -n "${allowed_jobs[$base_jid]+x}" ] || [ -n "${array_jobs[$base_jid]+x}" ]; then
          node_jobs+=("$jid")
        fi
      else
        [ "$stdout" = "N/A" ] && stdout=""
        [ "$workdir" = "N/A" ] && workdir=""
        if [[ -n "$target_dir_trim" && ( "$stdout" == "$target_prefix"* || "$workdir" == "$target_prefix"* || "$workdir" == "$target_dir_trim" ) ]]; then
          node_jobs+=("$jid")
        fi
      fi
    done < <(squeue -u "$username" -h -w "$node" -t R -o "%i|%o|%Z" 2>/dev/null || true)
    if [ ${#node_jobs[@]} -eq 0 ]; then
      echo "节点 $node 未找到可终止的作业"
      continue
    fi
    if [ "$count" -gt "${#node_jobs[@]}" ]; then
      count="${#node_jobs[@]}"
    fi
    if [ "$count" -le 0 ]; then
      echo "节点 $node 可终止作业数为0"
      continue
    fi
    echo "节点 $node 计划终止 $count 个作业"
    local j
    for ((j=0; j<count; j++)); do
      local jid="${node_jobs[$j]}"
      [ -z "$jid" ] && continue
      if [ -z "${kill_seen[$jid]+x}" ]; then
        kill_ids+=("$jid")
        kill_info+=("${jid}@${node}")
        kill_seen["$jid"]=1
      fi
    done
  done

  if [ ${#kill_ids[@]} -eq 0 ]; then
    echo "未找到可终止的作业"
    return 0
  fi

  echo "将终止以下作业 (jobid@node):"
  printf "%s\n" "${kill_info[@]}" | sort -u
  echo ""
  if kill_confirm "确认终止以上作业?"; then
    echo "正在删除任务..."
    for jid in "${kill_ids[@]}"; do
      echo "删除任务 $jid"
      scancel "$jid"
    done
    echo "完成终止节点作业"
  else
    echo "操作已取消"
  fi
}

kill_interactive_menu() {
  echo "请选择终止方式："
  echo "  [u] 按用户终止"
  echo "  [n] 按节点终止"
  echo "  [r] 按作业ID范围终止"
  echo "  [l] 按作业ID列表终止"
  echo "  [q] 退出"
  read -r -p "请输入选择 [u/n/r/l/q]: " choice || choice=""
  case "${choice,,}" in
    u)
      read -r -p "请输入用户名: " KILL_USER || KILL_USER=""
      [ -z "$KILL_USER" ] && echo "已取消（未提供用户名）" && return 0
      kill_user_jobs "$KILL_USER"
      ;;
    n)
      read -r -p "请输入节点列表 (node[:count], 逗号分隔): " KILL_NODE_SPEC || KILL_NODE_SPEC=""
      [ -z "$KILL_NODE_SPEC" ] && echo "已取消（未提供节点）" && return 0
      read -r -p "默认终止数量 (可留空): " KILL_COUNT || KILL_COUNT=""
      kill_node_jobs "$KILL_NODE_SPEC" "$KILL_COUNT" "$USER"
      ;;
    r)
      read -r -p "请输入范围 (开始-结束): " KILL_RANGE || KILL_RANGE=""
      [ -z "$KILL_RANGE" ] && echo "已取消（未提供范围）" && return 0
      kill_range_jobs "$KILL_RANGE"
      ;;
    l)
      read -r -p "请输入作业ID列表 (逗号分隔): " KILL_LIST || KILL_LIST=""
      [ -z "$KILL_LIST" ] && echo "已取消（未提供列表）" && return 0
      kill_list_jobs "$KILL_LIST"
      ;;
    q|quit|exit|"")
      echo "操作已取消"
      return 0
      ;;
    *)
      echo "无效选择"
      return 1
      ;;
  esac
}

handle_kill_command() {
  local cmd="${1:-}"
  if [ "$cmd" != "kill" ] && [ "$cmd" != "qdel" ] && [ "$cmd" != "--kill" ]; then
    return 1
  fi
  shift || true
  KILL_FORCE=0
  KILL_USER=""
  KILL_RANGE=""
  KILL_LIST=""
  KILL_NODE_SPEC=""
  KILL_COUNT=""
  while [ $# -ge 1 ]; do
    case "${1:-}" in
      -u|--user)
        KILL_USER="${2:-}"; shift 2 || true ;;
      -n|--node|--nodes)
        KILL_NODE_SPEC="${2:-}"; shift 2 || true ;;
      -c|--count)
        KILL_COUNT="${2:-}"; shift 2 || true ;;
      -r|--range)
        KILL_RANGE="${2:-}"; shift 2 || true ;;
      -l|--list|--ids)
        KILL_LIST="${2:-}"; shift 2 || true ;;
      -f|--force|--yes)
        KILL_FORCE=1; shift || true ;;
      -h|--help)
        kill_usage; return 0 ;;
      *)
        echo "无效参数: ${1:-}" >&2
        kill_usage
        exit 1 ;;
    esac
  done

  if [ -z "$KILL_USER" ] && [ -z "$KILL_RANGE" ] && [ -z "$KILL_LIST" ] && [ -z "$KILL_NODE_SPEC" ]; then
    if [ -t 0 ]; then
      kill_interactive_menu
      return 0
    else
      echo "错误: 请至少指定一种删除方式 (-u/-r/-l)" >&2
      kill_usage
      exit 1
    fi
  fi
  if [ -n "$KILL_NODE_SPEC" ]; then
    kill_node_jobs "$KILL_NODE_SPEC" "$KILL_COUNT" "${KILL_USER:-$USER}"
  elif [ -n "$KILL_USER" ]; then
    kill_user_jobs "$KILL_USER"
  fi
  [ -n "$KILL_RANGE" ] && kill_range_jobs "$KILL_RANGE"
  [ -n "$KILL_LIST" ] && kill_list_jobs "$KILL_LIST"
  return 0
}
