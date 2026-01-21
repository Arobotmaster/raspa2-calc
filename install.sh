#!/bin/bash

# RASPA 高通量计算工具安装脚本
# 版本: v2.5.0 (RASPA3 支持版本)
# 新增: RASPA2/RASPA3 双版本支持、自动版本检测、RASPA3 数据提取器

VERSION="2.5.0"

echo "=================================================="
echo "    RASPA 高通量计算工具 v${VERSION} 安装程序"
echo "=================================================="
echo ""

# 脚本配置
set -e  # 遇到错误立即退出
set -u  # 使用未定义变量时报错

# 复制工具函数
copy_dir_quiet() {
    local label="$1"
    local src="$2"
    local success_msg="${3:-✅ ${label} 复制完成}"

    if cp -r "$src" "$TOOL_DIR/" 2>/dev/null; then
        echo "$success_msg"
    else
        echo "⚠️  ${label} 复制失败或不存在"
    fi
}

copy_dir_with_header() {
    local label="$1"
    local src="$2"

    echo "正在复制 ${label} 目录..."
    copy_dir_quiet "$label" "$src" "${3:-}"
}

copy_file_quiet() {
    local label="$1"
    local src="$2"
    local success_msg="${3:-✅ ${label} 复制完成}"

    if cp "$src" "$TOOL_DIR/" 2>/dev/null; then
        echo "$success_msg"
    else
        echo "⚠️  ${label} 复制失败或不存在"
    fi
}

set_exec_for_dir() {
    local dir="$1"
    local label="$2"
    shift 2

    if [ ! -d "$dir" ]; then
        return
    fi

    echo "正在设置 ${label} 目录文件权限..."
    if [ "$#" -eq 0 ]; then
        find "$dir" -type f -exec chmod 755 {} \; 2>/dev/null
    else
        local pattern=""
        for pattern in "$@"; do
            find "$dir" -name "$pattern" -type f -exec chmod 755 {} \; 2>/dev/null
        done
    fi
    echo "✅ ${label} 目录文件权限设置完成"
}

detect_shell_config() {
    if [ "${ZSH_VERSION:-}" ]; then
        SHELL_RC="$HOME/.zshrc"
        SHELL_SOURCE="source ~/.zshrc"
    elif [ "${BASH_VERSION:-}" ]; then
        SHELL_RC="$HOME/.bashrc"
        SHELL_SOURCE="source ~/.bashrc"
    else
        SHELL_RC="$HOME/.profile"
        SHELL_SOURCE="source ~/.profile"
    fi
}

# 依赖检查函数
check_dependencies() {
    echo "🔍 检查系统依赖..."

    local missing_deps=()
    local warnings=()

    # 检查bash版本
    if ! bash --version >/dev/null 2>&1; then
        missing_deps+=("bash")
    fi

    local base_cmds=(find grep sed)
    local cmd=""
    for cmd in "${base_cmds[@]}"; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            missing_deps+=("$cmd")
        fi
    done

    if [ ${#missing_deps[@]} -ne 0 ]; then
        echo "❌ 缺少必要依赖: ${missing_deps[*]}"
        echo "请安装这些工具后再运行安装脚本"
        exit 1
    fi

    echo "✅ 系统工具检查通过"
    echo ""

    # ============ Python 环境检测 ============
    echo "🐍 检查 Python 环境..."
    
    # 检查 Python3 是否存在
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="python3"
    elif command -v python >/dev/null 2>&1; then
        # 检查 python 是否为 Python 3
        if python --version 2>&1 | grep -q "Python 3"; then
            PYTHON_CMD="python"
        else
            echo "❌ 未找到 Python 3，请安装 Python 3.8 或更高版本"
            exit 1
        fi
    else
        echo "❌ 未找到 Python，请安装 Python 3.8 或更高版本"
        exit 1
    fi

    # 检查 Python 版本
    PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PYTHON_MAJOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.major)")
    PYTHON_MINOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.minor)")

    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
        echo "❌ Python 版本过低: $PYTHON_VERSION (需要 3.8+)"
        exit 1
    fi

    echo "✅ Python $PYTHON_VERSION"

    # ============ Python 依赖包检测 ============
    echo ""
    echo "📦 检查 Python 依赖包..."
    
    local missing_packages=()
    local optional_missing=()

    # 必需包
    local required_packages=(yaml numpy pandas gemmi)
    local pkg=""
    for pkg in "${required_packages[@]}"; do
        if [ "$pkg" = "yaml" ]; then
            # yaml 包实际名为 PyYAML
            if $PYTHON_CMD -c "import yaml" 2>/dev/null; then
                echo "  ✅ yaml"
            else
                missing_packages+=("PyYAML")
                echo "  ❌ PyYAML (yaml) - 必需"
            fi
            continue
        fi

        if $PYTHON_CMD -c "import $pkg" 2>/dev/null; then
            echo "  ✅ $pkg"
        else
            missing_packages+=("$pkg")
            echo "  ❌ $pkg - 必需"
        fi
    done

    # 可选包
    local optional_packages=(tqdm openpyxl matplotlib)
    for pkg in "${optional_packages[@]}"; do
        if $PYTHON_CMD -c "import $pkg" 2>/dev/null; then
            echo "  ✅ $pkg (可选)"
        else
            optional_missing+=("$pkg")
            echo "  ⚠️  $pkg - 可选 (缺失)"
        fi
    done

    if [ ${#missing_packages[@]} -ne 0 ]; then
        echo ""
        echo "❌ 缺少必需的 Python 包: ${missing_packages[*]}"
        echo "   请运行: pip install ${missing_packages[*]}"
        echo ""
        read -p "是否继续安装? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "安装已取消"
            exit 1
        fi
        warnings+=("缺少 Python 包: ${missing_packages[*]}")
    fi

    if [ ${#optional_missing[@]} -ne 0 ]; then
        echo ""
        echo "💡 可选包安装命令: pip install ${optional_missing[*]}"
    fi

    echo ""

    # ============ RASPA 环境检测 ============
    echo "⚗️  检查 RASPA 环境..."
    
    local raspa2_found=false
    local raspa3_found=false
    local pymser_found=false
    local conda_base="${CONDA_PREFIX:-$HOME/anaconda3}"

    # 检查 RASPA2
    if [ -n "${RASPA_DIR:-}" ]; then
        if [ -x "$RASPA_DIR/bin/simulate" ]; then
            echo "  ✅ RASPA2: $RASPA_DIR/bin/simulate"
            raspa2_found=true
        else
            echo "  ⚠️  RASPA2: RASPA_DIR 已设置但 bin/simulate 不存在"
        fi
    else
        # 尝试常见位置
        for dir in "$HOME/anaconda3/pkgs/raspa2-"*/; do
            if [ -x "${dir}bin/simulate" ] 2>/dev/null; then
                echo "  ✅ RASPA2 (自动检测): ${dir}bin/simulate"
                raspa2_found=true
                break
            fi
        done
        if [ "$raspa2_found" = false ]; then
            echo "  ℹ️  RASPA2: 未检测到 (RASPA_DIR 未设置)"
        fi
    fi

    # 检查 RASPA3
    if command -v raspa3 >/dev/null 2>&1; then
        RASPA3_PATH=$(which raspa3)
        echo "  ✅ RASPA3: $RASPA3_PATH"
        raspa3_found=true
    else
        # 尝试在 conda 环境中查找
        for env_name in raspa3 RASPA3 raspa; do
            if [ -x "$conda_base/envs/$env_name/bin/raspa3" ]; then
                echo "  ✅ RASPA3 (conda $env_name): $conda_base/envs/$env_name/bin/raspa3"
                raspa3_found=true
                break
            fi
        done
        if [ "$raspa3_found" = false ]; then
            echo "  ℹ️  RASPA3: 未检测到 (可通过 conda 安装)"
        fi
    fi

    # 检查 pyMSER 环境 (pymser)
    if command -v conda >/dev/null 2>&1; then
        if conda env list | awk '{print $1}' | grep -qx "pymser"; then
            echo "  ✅ pymser 环境已存在 (pyMSER 用)"
            pymser_found=true
        else
            if [ -d "$conda_base/envs/pymser" ]; then
                echo "  ✅ pymser 环境已存在 (目录检测)"
                pymser_found=true
            else
                echo "  ℹ️  未检测到 pymser 环境（用于 pyMSER 自动平衡）"
            fi
        fi
    else
        echo "  ⚠️  未检测到 conda，无法检查/创建 raspa2/raspa3/pymser 环境"
    fi

    if [ "$raspa2_found" = false ] && [ "$raspa3_found" = false ]; then
        echo ""
        echo "⚠️  未检测到 RASPA2 或 RASPA3"
        echo "   请确保至少安装一个 RASPA 版本:"
        echo "   - RASPA2: 设置 export RASPA_DIR=/path/to/raspa2"
        echo "   - RASPA3: conda install -c conda-forge raspa3"
        echo ""
        warnings+=("未检测到 RASPA 安装")
    fi

    if command -v conda >/dev/null 2>&1; then
        if [ "$raspa2_found" = false ]; then
            warnings+=("缺少 raspa2 环境")
            echo "   建议：conda create --name raspa2 && conda activate raspa2 && conda install -c conda-forge raspa2"
        fi
        if [ "$raspa3_found" = false ]; then
            warnings+=("缺少 raspa3 环境")
            echo "   建议：conda create --name raspa3 && conda activate raspa3 && conda install -c conda-forge raspa3"
        fi
        if [ "$pymser_found" = false ]; then
            warnings+=("缺少 pymser 环境")
            echo "   建议：conda env create -f $HOME/raspa2-calc/.raspa_tools/environment.yml"
        fi
    fi

    echo ""

    # ============ 总结 ============
    if [ ${#warnings[@]} -ne 0 ]; then
        echo "⚠️  检测到以下警告:"
        for warn in "${warnings[@]}"; do
            echo "   • $warn"
        done
        echo ""
        echo "工具仍可安装，但部分功能可能无法使用"
    fi

    echo "✅ 环境预检测完成"
    echo ""
}

# 验证安装函数
validate_installation() {
    echo "🔍 验证安装..."

    local errors=()

    # 检查工具目录
    if [ ! -d "$TOOL_DIR" ]; then
        errors+=("工具目录不存在: $TOOL_DIR")
    fi

    # 检查关键可执行文件
    local key_files=("bin/raspa-status" "job_templates/runjobs.sh" "job_templates/tasksrun.sh")
    for file in "${key_files[@]}"; do
        if [ ! -f "$TOOL_DIR/$file" ]; then
            errors+=("关键文件缺失: $file")
        elif [ ! -x "$TOOL_DIR/$file" ]; then
            errors+=("文件无执行权限: $file")
        fi
    done

    # 检查关键目录
    local key_dirs=("raspa3json" "nfs")
    for dir in "${key_dirs[@]}"; do
        if [ ! -d "$TOOL_DIR/$dir" ]; then
            errors+=("关键目录缺失: $dir/")
        fi
    done

    if [ ${#errors[@]} -ne 0 ]; then
        echo "❌ 安装验证失败:"
        for error in "${errors[@]}"; do
            echo "   - $error"
        done
        return 1
    fi

    echo "✅ 安装验证通过"
    return 0
}

# 主函数
main() {
    echo "🚀 开始安装 RASPA 高通量计算工具 v${VERSION}..."
    echo ""

    # 检查依赖
    check_dependencies

    # 获取脚本所在目录（项目根目录）
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    echo "项目根目录: $SCRIPT_DIR"

# 设置工具目录
TOOL_DIR="$HOME/raspa2-calc/.raspa_tools"

# 预检查：若 NFS 挂载出现 Stale file handle，会导致 Slurm 作业 0 秒失败且无 stdout/err
if [ -d "$HOME/raspa2-calc" ]; then
    if ! ls -ld "$HOME/raspa2-calc" >/dev/null 2>&1; then
        echo "❌ 检测到目录无法访问: $HOME/raspa2-calc"
        echo "   这通常是 NFS 的 Stale file handle，先修复挂载再安装："
        echo "   - sudo umount -fl $HOME/raspa2-calc && sudo mount -a"
        echo "   - 或运行: bash \"$SCRIPT_DIR/nfs/nfs_client_setup.sh\" --recover"
        exit 1
    fi
fi

# 创建工具目录
echo "创建工具目录..."
mkdir -p "$TOOL_DIR"

# 复制所有项目文件到工具目录（排除.git和安装脚本本身）
echo "复制项目文件..."
copy_dir_with_header "bin/" "$SCRIPT_DIR/bin"

# 清理已整合的 main.sh
if [ -f "$TOOL_DIR/bin/main.sh" ]; then
    rm -f "$TOOL_DIR/bin/main.sh"
    echo "✅ 已移除旧的 main.sh (已整合到 raspa-calc)"
fi

copy_dir_with_header "job_templates/" "$SCRIPT_DIR/job_templates"

copy_dir_with_header "scripts/" "$SCRIPT_DIR/scripts"

# 清理已改为包入口的旧脚本
OLD_ALGO_FILES=(
    "scripts/python/auto_mser_raspa2.py"
    "scripts/python/auto_mser_raspa3.py"
    "scripts/python/calculate_params.py"
    "scripts/python/raspa3_generator.py"
    "scripts/python/cluster_info.py"
)
for old_file in "${OLD_ALGO_FILES[@]}"; do
    if [ -f "$TOOL_DIR/$old_file" ]; then
        rm -f "$TOOL_DIR/$old_file"
        echo "✅ 已移除旧脚本: $old_file"
    fi
done

# 清理已调整结构的旧模块/目录（避免旧文件残留）
LEGACY_PATHS=(
    "scripts/python/raspa_calc/commands"
    "scripts/python/raspa_calc/modes/auto.py"
    "scripts/python/raspa_calc/modes/task_runner.py"
    "scripts/python/task_runner/cif.py"
    "scripts/python/task_runner/cli.py"
    "scripts/python/task_runner/env.py"
    "scripts/python/task_runner/framework.py"
    "scripts/python/task_runner/inputs.py"
    "scripts/python/task_runner/logging_utils.py"
    "scripts/python/task_runner/scheduler.py"
    "scripts/python/task_runner/state.py"
    "scripts/python/task_runner/templates.py"
    "scripts/python/task_runner/__pycache__"
    "scripts/python/common/config.py"
    "scripts/python/common/__pycache__"
)
for legacy_path in "${LEGACY_PATHS[@]}"; do
    if [ -e "$TOOL_DIR/$legacy_path" ]; then
        rm -rf "$TOOL_DIR/$legacy_path"
        echo "✅ 已移除旧结构: $legacy_path"
    fi
done

copy_dir_with_header "raspa3json/" "$SCRIPT_DIR/raspa3json" "✅ raspa3json/ 复制完成（RASPA3 模板与分子库）"

copy_dir_with_header "raspa2-3/" "$SCRIPT_DIR/raspa2-3"

copy_dir_with_header "nfs/" "$SCRIPT_DIR/nfs" "✅ nfs/ 复制完成（NFS 挂载/修复脚本）"

echo "正在复制其他文件..."
copy_file_quiet "README.md" "$SCRIPT_DIR/README.md"
copy_file_quiet "qdel.sh" "$SCRIPT_DIR/qdel.sh"
copy_file_quiet "environment.yml" "$SCRIPT_DIR/environment.yml" "✅ environment.yml 复制完成（pymser 环境定义）"
copy_dir_quiet "docs/" "$SCRIPT_DIR/docs" "✅ docs/ 复制完成（说明文档）"

echo "正在复制配置文件..."
copy_file_quiet "config.yaml" "$SCRIPT_DIR/config.yaml"
copy_file_quiet "requirements.txt" "$SCRIPT_DIR/requirements.txt"

# 设置脚本权限
echo ""
echo "设置脚本执行权限..."

# 给所有.sh文件执行权限
echo "正在设置 .sh 文件权限..."
find "$TOOL_DIR" -name "*.sh" -type f -exec chmod 755 {} \; 2>/dev/null
echo "✅ 所有 .sh 文件权限设置完成"

# 给bin目录下的所有文件执行权限
set_exec_for_dir "$TOOL_DIR/bin" "bin/"
set_exec_for_dir "$TOOL_DIR/job_templates" "job_templates/"
set_exec_for_dir "$TOOL_DIR/scripts" "scripts/" "*.sh" "*.py"

# 特别确保关键可执行文件的权限
echo "正在设置关键可执行文件权限..."
EXECUTABLES=(
    "qdel.sh"
    "bin/raspa-scale"
    "bin/raspa-calc"
    "bin/raspa-status"
    "bin/raspa-diagnose"
    "bin/raspa-plot-isotherm"

    "job_templates/pbs.sh"
    "job_templates/local.sh"
    "job_templates/sbatch.sh"
    "job_templates/runjobs.sh"
    "job_templates/runjobs_raspa3.sh"
    "job_templates/tasksrun.sh"
    "job_templates/job_submit.sh"
    "job_templates/job_submit_ht.sh"

    "nfs/nfs_client_setup.sh"
    "nfs/nfs_setup_all_nodes.sh"
)

for exe in "${EXECUTABLES[@]}"; do
    if [ -f "$TOOL_DIR/$exe" ]; then
        chmod 755 "$TOOL_DIR/$exe"
        echo "✅ $exe 权限设置完成"
    else
        echo "⚠️  $exe 文件不存在"
    fi
done

# 检查并添加环境变量
echo ""
echo "配置环境变量..."
detect_shell_config

need_env_update=0
if ! grep -q "^export RASPA_TOOL_DIR=" "$SHELL_RC" 2>/dev/null; then
    need_env_update=1
fi
if ! grep -Fq "raspa2-calc/.raspa_tools/bin" "$SHELL_RC" 2>/dev/null; then
    need_env_update=1
fi

if [ "$need_env_update" -eq 1 ]; then
    echo "" >> "$SHELL_RC"
    echo "# RASPA2高通量计算工具" >> "$SHELL_RC"
    if ! grep -q "^export RASPA_TOOL_DIR=" "$SHELL_RC" 2>/dev/null; then
        echo "export RASPA_TOOL_DIR=\"$TOOL_DIR\"" >> "$SHELL_RC"
    fi
    if ! grep -Fq "raspa2-calc/.raspa_tools/bin" "$SHELL_RC" 2>/dev/null; then
        echo "export PATH=\"\$RASPA_TOOL_DIR/bin:\$PATH\"" >> "$SHELL_RC"
    fi
    echo "已添加环境变量配置到 $SHELL_RC"
else
    echo "环境变量配置已存在"
fi

# 立即生效环境变量
export RASPA_TOOL_DIR="$TOOL_DIR"
export PATH="$RASPA_TOOL_DIR/bin:$PATH"

# 清理旧的根目录软链（统一从 bin/ 调用）
echo ""
echo "清理旧的根目录软链接..."
for link in "$TOOL_DIR/raspa-status" "$TOOL_DIR/raspa-diagnose" "$TOOL_DIR/raspa-calc"; do
    if [ -L "$link" ]; then
        rm -f "$link" 2>/dev/null || true
        echo "✅ 已移除 $link"
    fi
done

echo ""
echo "=================================================="
echo "              安装完成！"
echo "=================================================="
echo ""
echo "🎉 RASPA 高通量计算工具 v${VERSION} 完整安装成功！"
echo ""
echo "📋 v${VERSION} 核心特性："
echo "   ✅ RASPA2/RASPA3 双版本支持 (自动检测版本，支持配置切换)"
echo "   ✅ RASPA3 数据提取器 (科学计数法格式解析)"
echo "   ✅ 自动版本检测 (simulation.json→RASPA3 / simulation.input→RASPA2)"
echo "   ✅ SLURM作业数组 (sbatch --array 提交速度快50倍)"
echo "   ✅ 共享任务队列 (原子竞争机制，减少90% NFS扫描)"
echo "   ✅ 动态并发缩放 (raspa-scale N 实时调整)"
echo "   ✅ 五大计算模式 (参数筛选/高通量/数据提取/警告处理/等温线绘制)"
echo "   ✅ 多节点集群支持 (NFS共享存储 + 960+ CPU核心)"
echo "   ✅ 原子文件锁机制 (基于POSIX noclobber的并发安全)"
echo "   ✅ 多调度系统支持 (SLURM/PBS/本地)"
echo "   ✅ 智能环境检测 (自动识别SLURM/PBS/LOCAL)"
echo "   ✅ 实时任务监控 (raspa-status精确统计)"
echo "   ✅ 警告处理系统 (失败任务提取 + CSV数据替换)"
echo ""
echo "📁 安装位置: $TOOL_DIR"
echo ""
echo "🗂️  NFS/集群提示："
echo "   - 若 Slurm 作业 0 秒失败且无 stdout/err，优先检查 NFS 是否报 Stale file handle"
echo "   - 单节点修复: bash \"$TOOL_DIR/nfs/nfs_client_setup.sh\" --recover"
echo "   - 批量修复: bash \"$TOOL_DIR/nfs/nfs_setup_all_nodes.sh\" recover --run"
echo ""
echo "🚀 快速开始："
echo "   1. 确认三个 conda 环境："
echo "      - raspa2: conda create --name raspa2 && conda activate raspa2 && conda install -c conda-forge raspa2"
echo "      - raspa3: conda create --name raspa3 && conda activate raspa3 && conda install -c conda-forge raspa3"
echo "      - pymser: conda env create -f \$HOME/raspa2-calc/.raspa_tools/environment.yml"
echo "   2. 重新加载shell环境:"
echo "      $SHELL_SOURCE"
echo "   3. 进入工作目录: cd /path/to/your/project"
echo "   4. 开始计算: raspa-calc 或 raspa-status"
echo ""
echo "🔧 可用命令："
echo "   - raspa-calc: 主计算工具"
echo "   - raspa-status: 状态检查工具"
echo "   - raspa-diagnose: 诊断工具"
echo ""
echo "📖 详细使用说明请查看 README.md"
echo ""
echo "⚙️  如需配置RASPA_DIR等环境变量，请参考文档"
echo ""

# 验证安装
if validate_installation; then
    echo ""
    echo "🎉 安装完成！所有验证通过。"
    echo ""
echo "💡 提示: 建议配置以下环境变量以获得最佳体验:"
echo "   export RASPA_DIR=/path/to/raspa/installation"
echo "   export RASPA_WORK_DIR=/path/to/work/directory"
echo "   export RASPA_TOOL_DIR=$TOOL_DIR"
else
    echo ""
    echo "⚠️  安装完成但存在一些问题，请检查上述错误信息。"
    exit 1
fi
}

# 执行主函数
main "$@"
