#!/usr/bin/env python3
import os
import re
import sys
import subprocess
import importlib

# 版本信息
__version__ = "2.5.0"
__version_name__ = "RASPA2/RASPA3 双版本支持"

# 全局配置
config = None

def load_config():
    """加载配置文件"""
    global config
    config_paths = [
        "config.yaml",  # 当前目录
        ".raspa_tools/config.yaml",  # 工具目录
        os.path.join(os.path.dirname(__file__), "../../config.yaml"),  # 脚本相对路径
        os.path.join(os.path.expanduser("~"), "raspa2-calc", ".raspa_tools", "config.yaml")  # 标准安装路径
    ]

    try:
        import yaml
        config_loaded = False

        for config_file in config_paths:
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                print(f"✅ 配置文件已加载: {config_file}")
                config_loaded = True
                break

        if not config_loaded:
            config = {}
            print("ℹ️  未找到配置文件，使用默认设置")
    except ImportError:
        config = {}
        print("⚠️  PyYAML未安装，使用默认设置")
    except Exception as e:
        config = {}
        print(f"⚠️  配置文件加载失败: {e}，使用默认设置")

def get_raspa_version():
    """获取配置的 RASPA 版本"""
    if config:
        version = config.get('environment', {}).get('raspa_version', 'raspa2')
        return version.lower() if version else 'raspa2'
    return 'raspa2'


def check_environment():
    """检测当前环境是否满足运行要求"""
    print("🔍 环境检测中...")
    print("=" * 50)

    all_passed = True
    issues = []

    # 0. 显示 RASPA 版本配置
    raspa_version = get_raspa_version()
    print(f"\n🔧 RASPA 版本: {raspa_version.upper()}")

    # 1. 检查Python依赖
    print("\n📦 检查Python依赖包:")
    python_deps = {
        'gemmi': '必需 - 用于精确CIF文件处理',
        'numpy': '必需 - 用于数值计算',
        'pandas': '必需 - 用于数据处理',
        'tqdm': '可选 - 用于进度条显示'
    }

    for package, description in python_deps.items():
        try:
            importlib.import_module(package)
            print(f"  ✅ {package} - {description}")
        except ImportError:
            if '必需' in description:
                print(f"  ❌ {package} - {description} (缺失)")
                issues.append(f"缺少必需的Python包: {package}")
                all_passed = False
            else:
                print(f"  ⚠️  {package} - {description} (缺失)")

    # 2. 检查系统工具
    print("\n🔧 检查系统工具:")
    system_tools = ['bash', 'find', 'grep', 'sed', 'chmod']

    for tool in system_tools:
        try:
            result = subprocess.run(['which', tool], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  ✅ {tool}")
            else:
                print(f"  ❌ {tool} (未找到)")
                issues.append(f"缺少系统工具: {tool}")
                all_passed = False
        except Exception:
            print(f"  ❌ {tool} (检查失败)")
            issues.append(f"无法检查系统工具: {tool}")
            all_passed = False

    # 3. 检查环境变量 (根据 RASPA 版本检查不同的变量)
    print("\n🌍 检查环境变量:")

    if raspa_version == 'raspa3':
        # RASPA3 不需要 RASPA_DIR，使用 conda 环境
        required_env_vars = ['RASPA_WORK_DIR']
    else:
        required_env_vars = ['RASPA_DIR', 'RASPA_WORK_DIR']

    for var in required_env_vars:
        # 优先使用配置文件中的设置
        config_value = config.get('environment', {}).get(var.lower(), '')
        env_value = os.environ.get(var, config_value)

        if env_value:
            print(f"  ✅ {var} = {env_value}")
        else:
            print(f"  ❌ {var} (未设置)")
            issues.append(f"缺少环境变量: {var}")
            all_passed = False

    # 4. 检查RASPA可执行文件 (根据版本检查不同的文件)
    print("\n⚙️  检查RASPA可执行文件:")

    if raspa_version == 'raspa3':
        # RASPA3: 检查 conda 环境中的 raspa3 命令
        raspa3_conda_env = config.get('environment', {}).get('raspa3_conda_env', 'raspa3')
        print(f"  ℹ️  RASPA3 Conda 环境: {raspa3_conda_env}")

        # 尝试检查 raspa3 命令是否可用
        try:
            # 检查 conda 环境目录
            conda_base = os.path.expanduser("~/anaconda3")
            if not os.path.exists(conda_base):
                conda_base = os.path.expanduser("~/miniconda3")

            raspa3_bin = os.path.join(conda_base, 'envs', raspa3_conda_env, 'bin', 'raspa3')
            if os.path.exists(raspa3_bin) and os.access(raspa3_bin, os.X_OK):
                print(f"  ✅ RASPA3 可执行文件: {raspa3_bin}")
            else:
                # 尝试用 which 命令查找
                result = subprocess.run(
                    f"source ~/anaconda3/etc/profile.d/conda.sh && conda activate {raspa3_conda_env} && which raspa3",
                    shell=True, capture_output=True, text=True, executable='/bin/bash'
                )
                if result.returncode == 0 and result.stdout.strip():
                    print(f"  ✅ RASPA3 可执行文件: {result.stdout.strip()}")
                else:
                    print(f"  ⚠️  RASPA3 可执行文件未找到 (请确保 {raspa3_conda_env} 环境已正确安装)")
                    print(f"     提示: conda activate {raspa3_conda_env} && which raspa3")
        except Exception as e:
            print(f"  ⚠️  无法检查 RASPA3 可执行文件: {e}")

        # 检查 RASPA3 配置路径
        raspa3_json_dir = config.get('environment', {}).get('raspa3_json_dir', '')
        raspa3_cif_base = config.get('environment', {}).get('raspa3_cif_base_path', '')
        raspa3_template = config.get('environment', {}).get('raspa3_template_path', '')

        print("\n📂 RASPA3 配置路径:")
        if raspa3_json_dir:
            if os.path.isdir(raspa3_json_dir):
                print(f"  ✅ JSON 文件目录: {raspa3_json_dir}")
            else:
                print(f"  ⚠️  JSON 文件目录不存在: {raspa3_json_dir}")
        else:
            print(f"  ℹ️  JSON 文件目录未配置 (raspa3_json_dir)")

        if raspa3_cif_base:
            if os.path.isdir(raspa3_cif_base):
                print(f"  ✅ CIF 基础路径: {raspa3_cif_base}")
            else:
                print(f"  ⚠️  CIF 基础路径不存在: {raspa3_cif_base}")
        else:
            print(f"  ⚠️  CIF 基础路径未配置 (raspa3_cif_base_path)")

        if raspa3_template:
            if os.path.isfile(raspa3_template):
                print(f"  ✅ 模板文件: {raspa3_template}")
            else:
                print(f"  ⚠️  模板文件不存在: {raspa3_template}")
        else:
            print(f"  ℹ️  模板文件未配置 (raspa3_template_path)")

    else:
        # RASPA2: 检查 RASPA_DIR/bin/simulate
        raspa_dir = os.environ.get('RASPA_DIR')
        if raspa_dir:
            simulate_path = os.path.join(raspa_dir, 'bin', 'simulate')
            if os.path.exists(simulate_path) and os.access(simulate_path, os.X_OK):
                print(f"  ✅ RASPA simulate 可执行文件: {simulate_path}")
            else:
                print(f"  ❌ RASPA simulate 可执行文件不存在或不可执行: {simulate_path}")
                issues.append("RASPA simulate 可执行文件不存在或不可执行")
                all_passed = False
        else:
            print("  ❌ 无法检查RASPA可执行文件 (RASPA_DIR未设置)")

    # 5. 检查工具目录
    print("\n📁 检查工具目录:")
    tool_dir = os.path.join(os.environ.get('HOME', ''), 'raspa2-calc', '.raspa_tools')
    if os.path.exists(tool_dir):
        print(f"  ✅ 工具目录存在: {tool_dir}")
    else:
        print(f"  ❌ 工具目录不存在: {tool_dir}")
        issues.append(f"工具目录不存在: {tool_dir}")
        all_passed = False

    # 总结
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 环境检测通过！所有要求都满足。")
        return True
    else:
        print("❌ 环境检测失败！发现以下问题:")
        for issue in issues:
            print(f"   • {issue}")
        print("\n请解决上述问题后再运行工具。")
        return False

def show_help():
    """显示帮助信息"""
    print(f"RASPA 高通量计算工具 v{__version__} ({__version_name__})")
    print()
    print("用法: raspa-calc [选项]")
    print()
    print("选项:")
    print("  -h, --help          显示此帮助信息")
    print("  -v, --version       显示版本信息")
    print("  --no-check          跳过环境检测")
    print()
    print("支持的 RASPA 版本:")
    print("  • RASPA2 - 传统版本 (simulation.input)")
    print("  • RASPA3 - 新版本 (simulation.json)")
    print("  在 config.yaml 中设置 raspa_version: 'raspa2' 或 'raspa3'")
    print()
    print("计算模式:")
    print("  1. 参数筛选模式（小批量运算）")
    print("     - 用于测试和参数优化")
    print("     - 默认使用2个CPU核心")
    print("     - 适合少量结构的快速验证")
    print()
    print("  2. 高通量计算模式（大规模计算）")
    print("     - 用于大规模计算")
    print("     - 支持用户指定CPU核心数")
    print("     - 支持多节点集群(960+CPU核心)")
    print("     - 自动检测任务数量并智能分配")
    print()
    print("  3. 数据提取模式（从计算结果中提取数据）")
    print("     - 从计算结果中提取关键数据")
    print("     - 自动检测 RASPA2/RASPA3 输出格式")
    print("     - 生成Excel表格")
    print()
    print("  4. 警告处理模式（处理计算中的警告任务）")
    print("     - 扫描CSV中的警告信息并创建独立任务")
    print()
    print("  5. 等温线绘制模式（批量绘制MOF等温吸附曲线）")
    print("     - 自动扫描计算结果目录并输出图片")
    print()
    print("  6. CSV/CIF 筛选模式（MOF筛选器）")
    print("     - 交互式按条件/refcode筛选CSV并可复制对应CIF")
    print()
    print("v2.5.0 新特性:")
    print("  ✅ CSV/CIF 筛选模式 - 直接从 raspa-calc 入口调用 MOF 筛选工具")
    print()
    print("v2.4.0 新特性:")
    print("  ✅ RASPA3 支持 - 完整支持 RASPA3 版本")
    print("  ✅ 版本自动检测 - 自动识别输出文件格式")
    print("  ✅ 双版本配置 - 配置文件支持切换版本")
    print()
    print("v2.3.0 特性:")
    print("  ✅ 多节点集群支持 - NFS共享存储实现跨节点调度")
    print("  ✅ 任务提交延迟优化 - 避免调度器过载导致节点异常")
    print("  ✅ 配置参数化 - 框架列名等参数完全可配置")
    print()
    print("示例:")
    print("  raspa-calc               # 交互式选择模式")
    print("  raspa-calc -h            # 显示帮助")
    print("  raspa-calc -v            # 显示版本")
    print()
    print("相关命令:")
    print("  raspa-status             # 查看任务状态")
    print("  raspa-diagnose           # 运行诊断")
    print()
    print("多节点集群使用:")
    print("  ⚠️  重要: 必须在NFS挂载目录下提交任务")
    print("  cd /home/zjp/raspa2-calc  # 进入NFS共享目录")
    print("  raspa-calc               # 启动高通量计算")
    print()

def show_version():
    """显示版本信息"""
    print(f"RASPA 高通量计算工具 v{__version__} ({__version_name__})")
    print()
    print("版本特性:")
    print("  ✅ CSV/CIF 筛选模式 - 直接在主菜单运行 MOF 筛选器")
    print("  ✅ RASPA2/RASPA3 双版本支持 - 可在配置文件中切换版本")
    print("  ✅ 版本自动检测 - 自动识别输出文件格式进行数据提取")
    print("  ✅ 多节点集群支持 - 支持SLURM集群跨节点调度(960+CPU核心)")
    print("  ✅ 任务提交优化 - 智能延迟避免调度器过载和Prolog error")
    print("  ✅ 配置参数化 - 支持从配置文件读取所有参数")
    print("  ✅ 精确UnitCells算法 - 基于向量叉积的精确计算")
    print("  ✅ gemmi库集成 - 专业CIF文件处理和晶体学计算")
    print()

def main():
    """RASPA计算工具主入口"""
    # 处理命令行参数
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ['-h', '--help']:
            show_help()
            return
        elif arg in ['-v', '--version']:
            show_version()
            return
        elif arg == '--no-check':
            skip_check = True
        else:
            print(f"错误: 未知参数 '{arg}'")
            print("使用 'raspa-calc -h' 查看帮助")
            sys.exit(1)
    else:
        skip_check = False

    print("Welcome to RASPA Calculation System")

    # 第一步：加载配置
    load_config()

    # 第二步：环境检测
    if not skip_check and not check_environment():
        print("\n💡 建议解决方案:")
        print("   1. 安装Python依赖: pip install gemmi numpy pandas")
        print("   2. 设置环境变量: export RASPA_DIR=/path/to/raspa")
        print("   3. 确保RASPA可执行文件存在且可执行")
        print("   4. 运行install.sh安装工具")
        sys.exit(1)

    # 显示版本信息
    raspa_version = get_raspa_version()
    print(f"\n🚀 当前版本: {__version__} ({__version_name__})")
    print(f"   • 当前 RASPA 版本: {raspa_version.upper()}")
    print("   • 支持 RASPA2/RASPA3 双版本切换")
    print("   • 支持多节点集群(NFS共享存储实现跨节点调度)")
    print("   • 配置参数化(支持从配置文件读取所有参数)")
    print("   • 集成gemmi库进行专业CIF处理")

    # 显示模式选择菜单
    print(f"\n=== RASPA计算模式选择 ({raspa_version.upper()}) ===")
    print("1. 参数筛选模式（小批量运算）")
    print("2. 高通量计算模式（大规模计算）")
    print("3. 数据提取模式（从计算结果中提取数据）")
    print("4. 警告处理模式（处理计算中的警告任务）")
    print("5. 等温线绘制模式（批量绘制MOF等温吸附曲线）")
    print("6. CSV/CIF 筛选模式（MOF筛选器）")
    print()
    print(f"💡 切换 RASPA 版本: 修改 config.yaml 中的 raspa_version 配置项")

    # 获取用户选择
    try:
        choice = input("请选择运行模式 (1/2/3/4/5/6): ").strip()

        if choice == '1':
            # 参数筛选模式
            run_auto_sh()
        elif choice == '2':
            # 高通量计算模式
            run_task_runner()
        elif choice == '3':
            # 数据提取模式
            run_data_extractor()
        elif choice == '4':
            # 警告处理模式
            run_warning_processor()
        elif choice == '5':
            # 等温线绘制模式
            run_isotherm_plotter()
        elif choice == '6':
            # CSV/CIF 筛选模式
            run_ciffilter_tool()
        else:
            print("无效的选择，请输入1、2、3、4、5或6")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n用户取消操作")
        sys.exit(130)
    except Exception as e:
        print(f"发生错误: {str(e)}")
        sys.exit(1)

def run_auto_sh():
    """运行参数筛选模式（小批量运算）"""
    try:
        # 与高通量模式保持一致：从配置导出关键环境变量（work_dir/cache_dir 等）
        if config:
            env_config = config.get('environment', {})
            calc_config = config.get('calculation', {})

            work_dir_cfg = env_config.get('work_dir') or os.environ.get('RASPA_WORK_DIR')
            if work_dir_cfg:
                os.environ['RASPA_WORK_DIR'] = work_dir_cfg
                try:
                    os.chdir(work_dir_cfg)
                except FileNotFoundError:
                    print(f"❌ 工作目录不存在: {work_dir_cfg}")
                    sys.exit(1)

            if 'cache_dir' in calc_config and calc_config['cache_dir']:
                os.environ['RASPA_CACHE_DIR'] = calc_config['cache_dir']

            raspa_ver = env_config.get('raspa_version', 'raspa2').lower()
            os.environ['RASPA_VERSION'] = raspa_ver
            if raspa_ver == 'raspa3':
                cif_path = env_config.get('raspa3_cif_base_path', '')
            else:
                cif_path = env_config.get('raspa2_cif_dir', '')
            if cif_path:
                os.environ['RASPA_CIF_DIR'] = cif_path

        # 获取工具目录
        tool_dir = os.environ.get('HOME', '') + '/raspa2-calc/.raspa_tools'
        auto_sh = os.path.join(tool_dir, "scripts/shell/auto.sh")
        
        if not os.path.exists(auto_sh):
            print(f"错误: 找不到脚本文件 {auto_sh}")
            sys.exit(1)
        
        # 执行auto.sh脚本
        os.system(f"bash {auto_sh}")
    except Exception as e:
        print(f"运行参数筛选模式时出错: {str(e)}")
        sys.exit(1)

def run_task_runner():
    """运行高通量计算模式（大规模计算）"""
    try:
        # 设置环境变量以传递配置参数
        if config:
            # 从配置文件读取参数并设置为环境变量
            env_config = config.get('environment', {})
            calc_config = config.get('calculation', {})

            # 统一工作目录：优先使用配置中的 work_dir，否则保持当前
            work_dir_cfg = env_config.get('work_dir') or os.environ.get('RASPA_WORK_DIR')
            if work_dir_cfg:
                os.environ['RASPA_WORK_DIR'] = work_dir_cfg
                try:
                    os.chdir(work_dir_cfg)
                except FileNotFoundError:
                    print(f"❌ 工作目录不存在: {work_dir_cfg}")
                    sys.exit(1)
            else:
                os.environ['RASPA_WORK_DIR'] = os.getcwd()

            # 根据 RASPA 版本设置 CIF 目录
            raspa_ver = env_config.get('raspa_version', 'raspa2').lower()
            if raspa_ver == 'raspa3':
                # RASPA3: 使用 raspa3_cif_base_path
                cif_path = env_config.get('raspa3_cif_base_path', '')
            else:
                # RASPA2: 使用 raspa2_cif_dir
                cif_path = env_config.get('raspa2_cif_dir', '')

            if cif_path:
                os.environ['RASPA_CIF_DIR'] = cif_path

            # 设置截断半径
            if 'cutoff_radius' in calc_config:
                os.environ['RASPA_CUTOFF_RADIUS'] = str(calc_config['cutoff_radius'])

            # 设置默认分子
            if 'default_molecules' in calc_config:
                os.environ['RASPA_DEFAULT_MOLECULES'] = calc_config['default_molecules']

            # 取消从配置文件读取并强制设置 CPU 核心数/最大结构数
            # cpu_cores 和 max_structures 将在提交高通量任务时由用户交互式设置

            # 设置输出目录
            if 'output_directory' in calc_config:
                os.environ['RASPA_OUTPUT_DIR'] = calc_config['output_directory']

            # 将本次使用的配置快照保存到输出目录，便于补交作业复用原配置
            try:
                out_dir_name = calc_config.get('output_directory')
                base_dir = os.environ.get('RASPA_WORK_DIR', os.getcwd())
                if out_dir_name and base_dir:
                    snap_dir = os.path.join(base_dir, out_dir_name)
                    os.makedirs(snap_dir, exist_ok=True)
                    snap_path = os.path.join(snap_dir, ".raspa_config.yaml")
                    try:
                        import yaml  # type: ignore
                        with open(snap_path, "w", encoding="utf-8") as fh:
                            yaml.safe_dump(config or {}, fh, allow_unicode=True)
                    except Exception:
                        import json
                        with open(snap_path, "w", encoding="utf-8") as fh:
                            fh.write(json.dumps(config or {}, ensure_ascii=False, indent=2))
                    print(f"ℹ️  当前配置已保存: {snap_path}")
            except Exception as save_err:
                print(f"⚠️  保存配置快照失败: {save_err}")

            # 设置 pyMSER 自动平衡参数
            mser_config = calc_config.get('mser', {})
            if mser_config:
                if 'enable' in mser_config:
                    os.environ['RASPA_MSER_ENABLE'] = str(mser_config.get('enable', False)).lower()
                if 'target_cycles' in mser_config:
                    os.environ['RASPA_MSER_TARGET_CYCLES'] = str(mser_config.get('target_cycles', 1000))
                if 'add_cycles' in mser_config:
                    os.environ['RASPA_MSER_ADD_CYCLES'] = str(mser_config.get('add_cycles', 500))
                if 'max_iter' in mser_config:
                    os.environ['RASPA_MSER_MAX_ITER'] = str(mser_config.get('max_iter', 20))
                if 'uncertainty' in mser_config:
                    os.environ['RASPA_MSER_UNCERTAINTY'] = mser_config.get('uncertainty', 'uSD')
                if 'conda_env' in mser_config:
                    os.environ['RASPA_MSER_CONDA_ENV'] = mser_config.get('conda_env', 'pymser')
                if 'llm' in mser_config:
                    os.environ['RASPA_MSER_LLM'] = str(mser_config.get('llm', True)).lower()
                if 'batch_size' in mser_config:
                    os.environ['RASPA_MSER_BATCH_SIZE'] = str(mser_config.get('batch_size', 5))

            # 设置模板相关参数 (根据 RASPA 版本选择正确的模板)
            raspa_version = env_config.get('raspa_version', 'raspa2').lower()

            if raspa_version == 'raspa3':
                # RASPA3: 使用 raspa3_template_path (simulation.json)
                if 'raspa3_template_path' in env_config and env_config['raspa3_template_path']:
                    os.environ['RASPA_TEMPLATE_PATH'] = env_config['raspa3_template_path']
            else:
                # RASPA2: 使用 template_path (simulation.input)
                if 'template_path' in env_config and env_config['template_path']:
                    os.environ['RASPA_TEMPLATE_PATH'] = env_config['template_path']

            # 节点优先级（可选），格式: node:priority,node2:priority
            if 'RASPA_NODE_PRIORITIES' not in os.environ:
                node_pri_cfg = env_config.get('node_priorities')
                if (not node_pri_cfg) and isinstance(calc_config.get('node_priorities'), dict):
                    node_pri_cfg = calc_config.get('node_priorities')
                if isinstance(node_pri_cfg, dict) and node_pri_cfg:
                    parts = []
                    for k, v in node_pri_cfg.items():
                        try:
                            parts.append(f"{k}:{int(v)}")
                        except Exception:
                            continue
                    if parts:
                        os.environ['RASPA_NODE_PRIORITIES'] = ",".join(parts)

            # 设置空隙率相关参数
            if 'use_void_csv' in calc_config:
                os.environ['RASPA_USE_VOID_CSV'] = str(calc_config['use_void_csv']).lower()

            if 'void_csv_file' in calc_config:
                os.environ['RASPA_VOID_CSV_FILE'] = calc_config['void_csv_file']

            if 'void_column' in calc_config:
                os.environ['RASPA_VOID_COLUMN'] = calc_config['void_column']

            if 'cache_dir' in calc_config and calc_config['cache_dir']:
                os.environ['RASPA_CACHE_DIR'] = calc_config['cache_dir']

            # 设置CSV文件路径
            if 'csv_file_path' in calc_config and calc_config['csv_file_path']:
                os.environ['RASPA_CSV_FILE'] = calc_config['csv_file_path']

            # 设置框架名称列
            if 'framework_column' in calc_config:
                os.environ['RASPA_FRAMEWORK_COLUMN'] = calc_config['framework_column']

            logging_config = config.get('logging', {})
            if 'output_dir' in logging_config and logging_config['output_dir']:
                os.environ['RASPA_JOB_LOG_DIR'] = logging_config['output_dir']
            else:
                os.environ.pop('RASPA_JOB_LOG_DIR', None)

            if 'enable_job_logs' in logging_config:
                os.environ['RASPA_ENABLE_JOB_LOGS'] = str(logging_config['enable_job_logs']).lower()
            else:
                os.environ.pop('RASPA_ENABLE_JOB_LOGS', None)

            # 工具目录（供 job 脚本引用）
            os.environ['RASPA_TOOL_DIR'] = os.path.expanduser("~/raspa2-calc/.raspa_tools")

            # ============ RASPA3 专用环境变量 ============
            # 设置 RASPA 版本 (raspa_version 已在上面定义)
            os.environ['RASPA_VERSION'] = raspa_version

            if raspa_version == 'raspa3':
                # RASPA3 Conda 环境名
                if 'raspa3_conda_env' in env_config:
                    os.environ['RASPA3_CONDA_ENV'] = env_config['raspa3_conda_env']

                # RASPA3 JSON 文件目录
                if 'raspa3_json_dir' in env_config and env_config['raspa3_json_dir']:
                    os.environ['RASPA3_JSON_DIR'] = env_config['raspa3_json_dir']

                # RASPA3 CIF 基础路径
                if 'raspa3_cif_base_path' in env_config and env_config['raspa3_cif_base_path']:
                    os.environ['RASPA3_CIF_BASE_PATH'] = env_config['raspa3_cif_base_path']

                # RASPA3 模板路径
                if 'raspa3_template_path' in env_config and env_config['raspa3_template_path']:
                    os.environ['RASPA3_TEMPLATE_PATH'] = env_config['raspa3_template_path']

                print(f"✅ 已设置 RASPA3 环境变量 (Conda环境: {env_config.get('raspa3_conda_env', 'raspa3')})")

            print("✅ 已从配置文件加载计算参数")

        # 导入task_runner模块
        from task_runner import main as task_runner_main
        task_runner_main()
    except ImportError:
        print("错误: 找不到task_runner模块")
        sys.exit(1)
    except Exception as e:
        print(f"运行高通量计算模式时出错: {str(e)}")
        sys.exit(1)

def run_warning_processor():
    """运行警告处理模式（处理计算中的警告任务）"""
    print("\n=== 警告处理模式 ===")
    print("该功能将分析CSV文件中的警告信息，并创建独立的警告任务")
    
    try:
        # 导入新的警告处理模块
        from warning_processor import main as warning_main
        warning_main()
    except ImportError as e:
        print(f"错误: 无法导入警告处理模块: {e}")
        print("请确保warning_processor.py文件在scripts/python目录中")
        sys.exit(1)
    except Exception as e:
        print(f"警告处理过程中出错: {e}")
        sys.exit(1)

def run_data_extractor():
    """运行数据提取模式（从计算结果中提取数据）"""
    print("\n=== 数据提取模式 ===")
    print("该功能将从计算结果中提取关键数据并生成Excel表格")

    try:
        # 导入数据提取模块
        from data_extractor import main as extract_main
        extract_main()
    except ImportError as e:
        print(f"错误: 无法导入数据提取模块: {e}")
        print("请确保data_extractor.py文件在scripts/python目录中")
        print("并且已安装所需的依赖库: pip install pandas tqdm")
        sys.exit(1)
    except Exception as e:
        print(f"数据提取过程中出错: {e}")
        sys.exit(1)

def run_isotherm_plotter():
    """运行等温线绘制模式（批量绘制MOF等温吸附曲线）"""
    print("\n=== 等温线绘制模式 ===")
    print("该功能将从RASPA计算结果中批量绘制所有MOF的等温吸附曲线")
    print()

    try:
        # 检查matplotlib依赖
        try:
            import matplotlib
        except ImportError:
            print("❌ 缺少必需的依赖库: matplotlib")
            print("请运行以下命令安装:")
            print("  pip install matplotlib")
            sys.exit(1)

        # 1. 检测参数筛选输出目录
        work_dir = os.getcwd()
        print(f"📁 当前工作目录: {work_dir}")

        def _detect_result_signals(dir_path: str) -> tuple[int, int]:
            """
            粗略检测目录是否包含可绘图的RASPA结果。

            Returns:
                (mc_count, raspa3_txt_count)
            """
            mc_count = 0
            raspa3_txt_count = 0

            # 1) mc* 目录（RASPA2/高通量结构）
            try:
                for entry in os.scandir(dir_path):
                    if not entry.is_dir():
                        continue
                    if re.match(r'^mc\\d+', entry.name):
                        mc_count += 1
            except Exception:
                pass

            # 2) RASPA3: */output/output_*.txt（参数筛选/JSON模板常见结构）
            def _count_txt_in_output(output_dir: str) -> int:
                n = 0
                try:
                    for f in os.scandir(output_dir):
                        if f.is_file():
                            name = f.name.lower()
                            if name.startswith('output_') and name.endswith('.txt'):
                                n += 1
                except Exception:
                    return 0
                return n

            # 当前目录自身可能就是一个任务目录
            raspa3_txt_count += _count_txt_in_output(os.path.join(dir_path, 'output'))

            # 或者当前目录下一级是任务目录
            try:
                for entry in os.scandir(dir_path):
                    if not entry.is_dir():
                        continue
                    raspa3_txt_count += _count_txt_in_output(os.path.join(entry.path, 'output'))
            except Exception:
                pass

            return mc_count, raspa3_txt_count

        # 获取配置中的输出目录名
        param_screening_config = config.get('parameter_screening', {}) if config else {}
        default_output_dir = param_screening_config.get('output_directory', '等温线')

        # 检测可能的输出目录
        possible_dirs = []

        # 优先检查几个常见目录名 + 当前目录本身
        for d in [default_output_dir, '等温线', 'output', 'calc_output', 'isotherms', '.']:
            full_path = work_dir if d == '.' else os.path.join(work_dir, d)
            if os.path.isdir(full_path):
                mc_count, raspa3_txt_count = _detect_result_signals(full_path)
                if mc_count > 0 or raspa3_txt_count > 0:
                    label = d
                    possible_dirs.append((label, full_path, mc_count, raspa3_txt_count))

        # 如果仍未命中，再扫描当前目录下的一级子目录（如: 单个MOF名目录）
        if not possible_dirs:
            try:
                for entry in os.scandir(work_dir):
                    if not entry.is_dir():
                        continue
                    mc_count, raspa3_txt_count = _detect_result_signals(entry.path)
                    if mc_count > 0 or raspa3_txt_count > 0:
                        possible_dirs.append((entry.name, entry.path, mc_count, raspa3_txt_count))
            except Exception:
                pass

        if possible_dirs:
            print(f"\n✓ 检测到 {len(possible_dirs)} 个包含计算结果的目录:")
            for i, (dirname, _, mc_count, raspa3_txt_count) in enumerate(possible_dirs, 1):
                parts = []
                if mc_count > 0:
                    parts.append(f"{mc_count} 个mc任务目录")
                if raspa3_txt_count > 0:
                    parts.append(f"{raspa3_txt_count} 个RASPA3输出文件")
                detail = "，".join(parts) if parts else "包含结果文件"
                suffix = "/" if dirname != "." else ""
                print(f"  {i}. {dirname}{suffix} ({detail})")
            print(f"  {len(possible_dirs) + 1}. 手动输入目录路径")
        else:
            print("\n⚠️  未检测到标准的计算结果目录")
            possible_dirs = []

        # 2. 获取用户选择的目录
        if possible_dirs:
            try:
                choice = input(f"\n请选择要绘制的目录 (1-{len(possible_dirs) + 1}) [默认: 1]: ").strip()
                if not choice:
                    choice = '1'

                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(possible_dirs):
                    base_dir = possible_dirs[choice_idx][1]
                elif choice_idx == len(possible_dirs):
                    base_dir = input("请输入目录路径: ").strip()
                    if not os.path.isdir(base_dir):
                        print(f"❌ 目录不存在: {base_dir}")
                        sys.exit(1)
                else:
                    print("❌ 无效的选择")
                    sys.exit(1)
            except ValueError:
                print("❌ 无效的输入")
                sys.exit(1)
        else:
            base_dir = input("请输入包含计算结果的目录路径: ").strip()
            if not os.path.isdir(base_dir):
                print(f"❌ 目录不存在: {base_dir}")
                sys.exit(1)

        # 3. 获取绘图参数（使用配置文件默认值）
        calc_config = config.get('calculation', {}) if config else {}

        print(f"\n📊 绘图参数配置:")
        print(f"   吸附类型: absolute (绝对吸附)")
        print(f"   单位: mol/kg")
        print(f"   压力单位: Pa")
        print(f"   x轴: 线性刻度")

        use_default = input("\n是否使用默认参数? (y/n) [默认: y]: ").strip().lower()

        if use_default in ['', 'y', 'yes']:
            ads_type = 'absolute'
            unit = 'mol/kg'
            pressure_unit = 'Pa'
            logx = False
        else:
            ads_type = input("吸附类型 (absolute/excess) [默认: absolute]: ").strip() or 'absolute'
            unit = input("单位 (mol/kg, cm^3/g, mg/g, cm^3/cm^3) [默认: mol/kg]: ").strip() or 'mol/kg'
            pressure_unit = input("压力单位 (Pa/bar) [默认: Pa]: ").strip() or 'Pa'
            logx_input = input("使用对数x轴? (y/n) [默认: n]: ").strip().lower()
            logx = logx_input in ['y', 'yes']

        # 4. 输出目录
        outdir = input(f"\n输出目录名 [默认: isotherms]: ").strip() or 'isotherms'

        # 5. 调用等温线绘制工具
        print(f"\n🚀 开始绘制等温线...")
        print(f"   扫描目录: {base_dir}")
        print(f"   输出目录: {outdir}")

        from isotherm_plotter import main as plotter_main

        # 构造参数列表
        args = [
            '--base-dir', base_dir,
            '--type', ads_type,
            '--unit', unit,
            '--pressure-unit', pressure_unit,
            '--outdir', outdir,
        ]

        if logx:
            args.append('--logx')
        else:
            args.append('--linearx')

        # 运行绘图工具
        plotter_main(args)

    except ImportError as e:
        print(f"❌ 无法导入等温线绘制模块: {e}")
        print("请确保 isotherm_plotter.py 文件在 scripts/python 目录中")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  用户取消操作")
        sys.exit(130)
    except Exception as e:
        print(f"❌ 等温线绘制过程中出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def run_ciffilter_tool():
    """运行 CSV/CIF 筛选模式（MOF筛选器）"""
    print("\n=== CSV/CIF 筛选模式 ===")
    print("该功能按条件/refcode筛选CSV并可选择复制对应的CIF文件")

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        tool_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
        default_tool_dir = os.path.join(os.environ.get('HOME', ''), 'raspa2-calc', '.raspa_tools')

        for path in [tool_dir, default_tool_dir]:
            if path and path not in sys.path:
                sys.path.insert(0, path)

        try:
            from ciffilter import MOFFilterTool
        except ImportError as e:
            print(f"错误: 无法导入 CSV/CIF 筛选工具: {e}")
            print(f"请确认 ciffilter.py 位于 {tool_dir}，并已安装 pandas 等依赖")
            sys.exit(1)

        tool = MOFFilterTool()
        tool.run()
    except KeyboardInterrupt:
        print("\n⚠️  用户取消操作")
        sys.exit(130)
    except Exception as e:
        print(f"❌ CSV/CIF 筛选过程中出错: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
