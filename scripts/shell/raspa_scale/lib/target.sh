prepare_target_dir() {
  # 尝试在当前路径向上寻找 job_templates 目录
  BASE_DIR="$ABS_PWD"
  while [ "$BASE_DIR" != "/" ] && [ ! -d "$BASE_DIR/job_templates" ]; do
    BASE_DIR="$(dirname "$BASE_DIR")"
  done
  if [ ! -d "$BASE_DIR/job_templates" ]; then
    echo "错误: 未在当前路径及其父目录中找到 job_templates，请在项目工作目录下执行" >&2
    exit 1
  fi

  # 计算当前目录相对于 BASE_DIR 的子路径
  if [ "$ABS_PWD" = "$BASE_DIR" ]; then
    DEFAULT_SUBDIR="."
  else
    DEFAULT_SUBDIR="${ABS_PWD#$BASE_DIR/}"
  fi

  # 解析子目录（若传入则使用，否则自动检测）
  if [ -n "$RAW_SUBDIR" ]; then
    SUBDIR="$RAW_SUBDIR"
  else
    SUBDIR="$DEFAULT_SUBDIR"
  fi

  # 初步定位目标目录
  if [ "$SUBDIR" = "." ]; then
    TARGET_DIR="$BASE_DIR"
  else
    TARGET_DIR="$BASE_DIR/$SUBDIR"
  fi

  check_disk_space "$TARGET_DIR"
  TARGET_DIR="$(cd "$TARGET_DIR" && pwd -P)"
  if [ ! -d "$TARGET_DIR" ]; then
    echo "错误: 目标目录不存在: $TARGET_DIR" >&2
    exit 1
  fi

  # 智能选择：当未显式指定子目录且当前层没有任务，但仅有一个子目录包含任务时，自动切换到该子目录
  if [ -z "$RAW_SUBDIR" ] && [ "$SUBDIR" = "." ]; then
    HAS_TASKS=""
    if [ -f "$TARGET_DIR/.raspa_queue/tasks.list" ] && grep -q '[^[:space:]]' "$TARGET_DIR/.raspa_queue/tasks.list" 2>/dev/null; then
      HAS_TASKS="yes"
    else
      HAS_TASKS=$(find "$TARGET_DIR" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -print -quit 2>/dev/null)
    fi
    if [ -z "$HAS_TASKS" ]; then
      mapfile -t CANDIDATES < <(find "$TARGET_DIR" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | while read -r d; do
        if [ -f "$d/.raspa_queue/tasks.list" ] && grep -q '[^[:space:]]' "$d/.raspa_queue/tasks.list" 2>/dev/null; then
          basename "$d"
          continue
        fi
        find "$d" -maxdepth 1 -type d -name 'mc[0-9]*' ! -name '*__*' -print -quit 2>/dev/null | grep -q . && basename "$d"
      done)
      # 去重
      if [ ${#CANDIDATES[@]} -eq 1 ]; then
        SUBDIR="${CANDIDATES[0]}"
        TARGET_DIR="$BASE_DIR/$SUBDIR"
        TARGET_DIR="$(cd "$TARGET_DIR" && pwd -P)"
        echo "检测到唯一包含任务的子目录: $SUBDIR -> 切换目标目录为: $TARGET_DIR"
      fi
    fi
  fi

  echo "工作根目录: $BASE_DIR"
  echo "目标子目录: $SUBDIR"

  # 若任务目录下不存在配置快照，尝试复制当前可用的 config.yaml，确保补交作业继承配置
  CONFIG_SNAPSHOT="$TARGET_DIR/.raspa_config.yaml"
  if [ ! -f "$CONFIG_SNAPSHOT" ]; then
    for candidate in "$TARGET_DIR/config.yaml" "$BASE_DIR/config.yaml" "$ROOT_DIR/.raspa_tools/config.yaml"; do
      if [ -f "$candidate" ]; then
        cp -f "$candidate" "$CONFIG_SNAPSHOT" 2>/dev/null && echo "已生成配置快照: $CONFIG_SNAPSHOT"
        break
      fi
    done
  fi

  # 自动检测 RASPA 版本（若环境变量未设置）
  if [ -z "${RASPA_VERSION:-}" ]; then
    # 检测第一个存在的任务目录（避免管道SIGPIPE，使用 -print -quit）
    SAMPLE_DIR=""
    if [ -f "$TARGET_DIR/.raspa_queue/tasks.list" ]; then
      SAMPLE_REL=$(grep -m1 -E '\S' "$TARGET_DIR/.raspa_queue/tasks.list" 2>/dev/null | head -1)
      if [ -n "$SAMPLE_REL" ]; then
        base_path="$TARGET_DIR/${SAMPLE_REL%/}"
        for cand in "$base_path" "${base_path}__running" "${base_path}__done" "${base_path}__failed"; do
          if [ -d "$cand" ]; then
            SAMPLE_DIR="$cand"
            break
          fi
        done
      fi
    fi
    if [ -z "$SAMPLE_DIR" ]; then
      SAMPLE_DIR=$(find "$TARGET_DIR" -maxdepth 1 -type d \( -name 'mc[0-9]*' -o -name 'mc[0-9]*__running' \) -print -quit 2>/dev/null)
    fi
    if [ -n "$SAMPLE_DIR" ]; then
      if [ -f "$SAMPLE_DIR/simulation.json" ]; then
        RASPA_VERSION="raspa3"
        echo "检测到 RASPA3 任务 (simulation.json)"
      elif [ -f "$SAMPLE_DIR/simulation.input" ]; then
        RASPA_VERSION="raspa2"
        echo "检测到 RASPA2 任务 (simulation.input)"
      fi
    fi
    # 默认 RASPA2
    [ -z "${RASPA_VERSION:-}" ] && RASPA_VERSION="raspa2"
  fi
  export RASPA_VERSION
}
