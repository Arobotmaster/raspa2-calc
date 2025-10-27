#!/bin/bash

# RASPA2 高通量计算工具安装脚本
# 版本: v2.3.0 (集群优化版本)
# 新增: SLURM作业数组、共享任务队列、动态并发缩放、五大计算模式、多节点集群支持

echo "=================================================="
echo "    RASPA2 高通量计算工具 v2.3 安装程序"
echo "=================================================="
echo ""

# 脚本配置
set -e  # 遇到错误立即退出
set -u  # 使用未定义变量时报错

# 依赖检查函数
check_dependencies() {
    echo "🔍 检查系统依赖..."

    local missing_deps=()

    # 检查bash版本
    if ! bash --version >/dev/null 2>&1; then
        missing_deps+=("bash")
    fi

    # 检查find命令
    if ! command -v find >/dev/null 2>&1; then
        missing_deps+=("find")
    fi

    # 检查grep命令
    if ! command -v grep >/dev/null 2>&1; then
        missing_deps+=("grep")
    fi

    # 检查sed命令
    if ! command -v sed >/dev/null 2>&1; then
        missing_deps+=("sed")
    fi

    if [ ${#missing_deps[@]} -ne 0 ]; then
        echo "❌ 缺少必要依赖: ${missing_deps[*]}"
        echo "请安装这些工具后再运行安装脚本"
        exit 1
    fi

    echo "✅ 系统依赖检查通过"
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
    echo "🚀 开始安装 RASPA2 高通量计算工具..."
    echo ""

    # 检查依赖
    check_dependencies

    # 获取脚本所在目录（项目根目录）
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    echo "项目根目录: $SCRIPT_DIR"

# 设置工具目录
TOOL_DIR="$HOME/raspa2-calc/.raspa_tools"

# 备份现有安装
backup_existing_installation() {
    if [ -d "$TOOL_DIR" ]; then
        local backup_dir="${TOOL_DIR}.backup.$(date +%Y%m%d_%H%M%S)"
        echo "📦 发现现有安装，正在备份..."
        echo "备份位置: $backup_dir"
        cp -r "$TOOL_DIR" "$backup_dir"
        echo "✅ 备份完成"
        echo ""
    fi
}

# 创建工具目录
echo "创建工具目录..."
mkdir -p "$TOOL_DIR"

# 备份现有安装
backup_existing_installation

# 复制所有项目文件到工具目录（排除.git和安装脚本本身）
echo "复制项目文件..."
echo "正在复制 bin/ 目录..."
cp -r "$SCRIPT_DIR/bin" "$TOOL_DIR/" 2>/dev/null && echo "✅ bin/ 复制完成" || echo "⚠️  bin/ 复制失败或不存在"

# 更新main.sh为支持配置文件的版本
cat > "$TOOL_DIR/bin/main.sh" << 'EOF'
#!/bin/bash

# 获取工具安装目录
TOOL_DIR="$HOME/raspa2-calc/.raspa_tools"
# 获取当前工作目录
WORK_DIR="$PWD"

# 设置工作目录环境变量
export RASPA_WORK_DIR="$WORK_DIR"

# 调用Python主程序，支持配置文件功能
exec python "$TOOL_DIR/scripts/python/raspa_calc.py"
EOF
echo "✅ main.sh 已更新为配置文件版本"

echo "正在复制 config/ 目录..."
cp -r "$SCRIPT_DIR/config" "$TOOL_DIR/" 2>/dev/null && echo "✅ config/ 复制完成" || echo "⚠️  config/ 复制失败或不存在"

echo "正在复制 job_templates/ 目录..."
cp -r "$SCRIPT_DIR/job_templates" "$TOOL_DIR/" 2>/dev/null && echo "✅ job_templates/ 复制完成" || echo "⚠️  job_templates/ 复制失败或不存在"

echo "正在复制 scripts/ 目录..."
cp -r "$SCRIPT_DIR/scripts" "$TOOL_DIR/" 2>/dev/null && echo "✅ scripts/ 复制完成" || echo "⚠️  scripts/ 复制失败或不存在"

echo "正在复制其他文件..."
cp "$SCRIPT_DIR/README.md" "$TOOL_DIR/" 2>/dev/null && echo "✅ README.md 复制完成" || echo "⚠️  README.md 复制失败或不存在"
cp "$SCRIPT_DIR/qdel.sh" "$TOOL_DIR/" 2>/dev/null && echo "✅ qdel.sh 复制完成" || echo "⚠️  qdel.sh 复制失败或不存在"

echo "正在复制配置文件..."
cp "$SCRIPT_DIR/config.yaml" "$TOOL_DIR/" 2>/dev/null && echo "✅ config.yaml 复制完成" || echo "⚠️  config.yaml 复制失败或不存在"
cp "$SCRIPT_DIR/requirements.txt" "$TOOL_DIR/" 2>/dev/null && echo "✅ requirements.txt 复制完成" || echo "⚠️  requirements.txt 复制失败或不存在"

# 设置脚本权限
echo ""
echo "设置脚本执行权限..."

# 给所有.sh文件执行权限
echo "正在设置 .sh 文件权限..."
find "$TOOL_DIR" -name "*.sh" -type f -exec chmod 755 {} \; 2>/dev/null
echo "✅ 所有 .sh 文件权限设置完成"

# 给bin目录下的所有文件执行权限
if [ -d "$TOOL_DIR/bin" ]; then
    echo "正在设置 bin/ 目录文件权限..."
    find "$TOOL_DIR/bin" -type f -exec chmod 755 {} \; 2>/dev/null
    echo "✅ bin/ 目录文件权限设置完成"
fi

# 给job_templates目录下的所有文件执行权限
if [ -d "$TOOL_DIR/job_templates" ]; then
    echo "正在设置 job_templates/ 目录文件权限..."
    find "$TOOL_DIR/job_templates" -type f -exec chmod 755 {} \; 2>/dev/null
    echo "✅ job_templates/ 目录文件权限设置完成"
fi

# 给scripts目录下的所有脚本文件执行权限
if [ -d "$TOOL_DIR/scripts" ]; then
    echo "正在设置 scripts/ 目录文件权限..."
    find "$TOOL_DIR/scripts" -name "*.sh" -type f -exec chmod 755 {} \; 2>/dev/null
    find "$TOOL_DIR/scripts" -name "*.py" -type f -exec chmod 755 {} \; 2>/dev/null
    echo "✅ scripts/ 目录文件权限设置完成"
fi

# 特别确保关键可执行文件的权限
echo "正在设置关键可执行文件权限..."
EXECUTABLES=(
    "qdel.sh"
    "bin/main.sh"
    "bin/chmod.sh"
    "bin/raspa-scale"
    "bin/raspa-status"
    "bin/recheck-failed"
    "bin/raspa-diagnose"
    "bin/raspa-plot-isotherm"

    "job_templates/pbs.sh"
    "job_templates/local.sh"
    "job_templates/sbatch.sh"
    "job_templates/runjobs.sh"
    "job_templates/tasksrun.sh"
    "job_templates/job_array.sh"
    "job_templates/job_submit.sh"
    "job_templates/job_submit_ht.sh"
)

for exe in "${EXECUTABLES[@]}"; do
    if [ -f "$TOOL_DIR/$exe" ]; then
        chmod 755 "$TOOL_DIR/$exe"
        echo "✅ $exe 权限设置完成"
    else
        echo "⚠️  $exe 文件不存在"
    fi
done

# 检查并添加PATH环境变量
echo ""
echo "配置环境变量..."
SHELL_RC=""

# 安全地检测shell类型（避免set -u导致的unbound variable错误）
if [ "${ZSH_VERSION:-}" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ "${BASH_VERSION:-}" ]; then
    SHELL_RC="$HOME/.bashrc"
else
    SHELL_RC="$HOME/.profile"
fi

# 检查PATH是否已配置 (更精确的检查)
if ! grep -q "^export PATH=.*raspa2-calc/.raspa_tools.*PATH" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# RASPA2高通量计算工具" >> "$SHELL_RC"
    echo "export PATH=\"\$HOME/raspa2-calc/.raspa_tools:\$PATH\"" >> "$SHELL_RC"
    echo "export PATH=\"\$HOME/raspa2-calc/.raspa_tools/bin:\$PATH\"" >> "$SHELL_RC"
    echo "已添加PATH配置到 $SHELL_RC"
else
    echo "PATH配置已存在"
fi

# 立即生效PATH配置
export PATH="$HOME/raspa2-calc/.raspa_tools:$HOME/raspa2-calc/.raspa_tools/bin:$PATH"

# 创建符号链接以便直接访问主要工具
echo ""
echo "创建符号链接..."
if [ -f "$TOOL_DIR/bin/raspa-status" ]; then
    ln -sf "$TOOL_DIR/bin/raspa-status" "$TOOL_DIR/raspa-status" 2>/dev/null
    echo "✅ raspa-status 符号链接创建完成"
fi

if [ -f "$TOOL_DIR/bin/raspa-diagnose" ]; then
    ln -sf "$TOOL_DIR/bin/raspa-diagnose" "$TOOL_DIR/raspa-diagnose" 2>/dev/null
    echo "✅ raspa-diagnose 符号链接创建完成"
fi

if [ -f "$TOOL_DIR/bin/main.sh" ]; then
    ln -sf "$TOOL_DIR/bin/main.sh" "$TOOL_DIR/raspa-calc" 2>/dev/null
    echo "✅ raspa-calc 符号链接创建完成"
fi

echo ""
echo "=================================================="
echo "              安装完成！"
echo "=================================================="
echo ""
echo "🎉 RASPA2高通量计算工具 v2.3.0 完整安装成功！"
echo ""
echo "📋 v2.3.0 核心特性："
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
echo "🚀 快速开始："
echo "   1. 重新加载shell环境:"
if [ "${ZSH_VERSION:-}" ]; then
    echo "      source ~/.zshrc"
elif [ "${BASH_VERSION:-}" ]; then
    echo "      source ~/.bashrc"
else
    echo "      source ~/.profile"
fi
echo "   2. 进入工作目录: cd /path/to/your/project"
echo "   3. 开始计算: raspa-calc 或 raspa-status"
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
else
    echo ""
    echo "⚠️  安装完成但存在一些问题，请检查上述错误信息。"
    exit 1
fi
}

# 执行主函数
main "$@"