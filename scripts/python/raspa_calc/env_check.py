import importlib
import os
import shutil
import subprocess

from . import config as config_module


def check_disk_space():
    """Check work dir free space; default warn-only."""
    work_dir = config_module._get_work_dir()
    if not work_dir:
        return True

    min_free_gb = None
    action = None
    if config_module.config:
        env_cfg = config_module.config.get("environment", {}) or {}
        min_free_gb = env_cfg.get("work_dir_min_free_gb")
        action = env_cfg.get("work_dir_min_free_action")

    if os.environ.get("RASPA_MIN_FREE_GB"):
        min_free_gb = os.environ.get("RASPA_MIN_FREE_GB")
    if os.environ.get("RASPA_MIN_FREE_ACTION"):
        action = os.environ.get("RASPA_MIN_FREE_ACTION")

    try:
        min_free_gb = int(min_free_gb) if min_free_gb is not None else 50
    except Exception:
        min_free_gb = 50

    action = (str(action).strip().lower() if action else "warn")
    if action not in ("warn", "abort"):
        action = "warn"

    try:
        usage = shutil.disk_usage(work_dir)
        free_gb = int(usage.free / (1024 ** 3))
    except Exception as exc:
        print(f"⚠️  无法检查工作目录剩余空间: {exc}")
        return True

    if free_gb < min_free_gb:
        msg = (
            f"⚠️  磁盘空间不足警告: {work_dir}\n"
            f"   当前剩余: {free_gb} GB，安全阈值: {min_free_gb} GB"
        )
        print(msg)
        if action == "abort":
            print("❌ 空间不足，已阻断执行，请清理或归档后再运行。")
            return False
    return True


def check_environment():
    """Check environment requirements."""
    print("🔍 环境检测中...")
    print("=" * 50)

    all_passed = True
    issues = []

    # 0. Display configured version
    raspa_version = config_module.get_raspa_version()
    print(f"\n🔧 RASPA 版本: {raspa_version.upper()}")

    # 1. Python deps
    print("\n📦 检查Python依赖包:")
    python_deps = {
        "gemmi": "必需 - 用于精确CIF文件处理",
        "numpy": "必需 - 用于数值计算",
        "pandas": "必需 - 用于数据处理",
        "tqdm": "可选 - 用于进度条显示",
    }

    for package, description in python_deps.items():
        try:
            importlib.import_module(package)
            print(f"  ✅ {package} - {description}")
        except ImportError:
            if "必需" in description:
                print(f"  ❌ {package} - {description} (缺失)")
                issues.append(f"缺少必需的Python包: {package}")
                all_passed = False
            else:
                print(f"  ⚠️  {package} - {description} (缺失)")

    # 2. System tools
    print("\n🔧 检查系统工具:")
    system_tools = ["bash", "find", "grep", "sed", "chmod"]

    for tool in system_tools:
        try:
            result = subprocess.run(["which", tool], capture_output=True, text=True)
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

    # 3. Env vars
    print("\n🌍 检查环境变量:")

    if raspa_version == "raspa3":
        required_env_vars = ["RASPA_WORK_DIR"]
    else:
        required_env_vars = ["RASPA_DIR", "RASPA_WORK_DIR"]

    for var in required_env_vars:
        # Prefer config
        config_value = config_module.config.get("environment", {}).get(var.lower(), "") if config_module.config else ""
        env_value = os.environ.get(var, config_value)

        if env_value:
            print(f"  ✅ {var} = {env_value}")
        else:
            print(f"  ❌ {var} (未设置)")
            issues.append(f"缺少环境变量: {var}")
            all_passed = False

    # 4. RASPA executable
    print("\n⚙️  检查RASPA可执行文件:")

    if raspa_version == "raspa3":
        raspa3_conda_env = config_module.config.get("environment", {}).get("raspa3_conda_env", "raspa3") if config_module.config else "raspa3"
        print(f"  ℹ️  RASPA3 Conda 环境: {raspa3_conda_env}")

        try:
            conda_base = os.path.expanduser("~/anaconda3")
            if not os.path.exists(conda_base):
                conda_base = os.path.expanduser("~/miniconda3")

            raspa3_bin = os.path.join(conda_base, "envs", raspa3_conda_env, "bin", "raspa3")
            if os.path.exists(raspa3_bin) and os.access(raspa3_bin, os.X_OK):
                print(f"  ✅ RASPA3 可执行文件: {raspa3_bin}")
            else:
                result = subprocess.run(
                    f"source ~/anaconda3/etc/profile.d/conda.sh && conda activate {raspa3_conda_env} && which raspa3",
                    shell=True,
                    capture_output=True,
                    text=True,
                    executable="/bin/bash",
                )
                if result.returncode == 0 and result.stdout.strip():
                    print(f"  ✅ RASPA3 可执行文件: {result.stdout.strip()}")
                else:
                    print(f"  ⚠️  RASPA3 可执行文件未找到 (请确保 {raspa3_conda_env} 环境已正确安装)")
                    print(f"     提示: conda activate {raspa3_conda_env} && which raspa3")
        except Exception as e:
            print(f"  ⚠️  无法检查 RASPA3 可执行文件: {e}")

        # RASPA3 config paths
        raspa3_json_dir = config_module.config.get("environment", {}).get("raspa3_json_dir", "") if config_module.config else ""
        raspa3_cif_base = config_module.config.get("environment", {}).get("raspa3_cif_base_path", "") if config_module.config else ""
        raspa3_template = config_module.config.get("environment", {}).get("raspa3_template_path", "") if config_module.config else ""

        print("\n📂 RASPA3 配置路径:")
        if raspa3_json_dir:
            if os.path.isdir(raspa3_json_dir):
                print(f"  ✅ JSON 文件目录: {raspa3_json_dir}")
            else:
                print(f"  ⚠️  JSON 文件目录不存在: {raspa3_json_dir}")
        else:
            print("  ℹ️  JSON 文件目录未配置 (raspa3_json_dir)")

        if raspa3_cif_base:
            if os.path.isdir(raspa3_cif_base):
                print(f"  ✅ CIF 基础路径: {raspa3_cif_base}")
            else:
                print(f"  ⚠️  CIF 基础路径不存在: {raspa3_cif_base}")
        else:
            print("  ⚠️  CIF 基础路径未配置 (raspa3_cif_base_path)")

        if raspa3_template:
            if os.path.isfile(raspa3_template):
                print(f"  ✅ 模板文件: {raspa3_template}")
            else:
                print(f"  ⚠️  模板文件不存在: {raspa3_template}")
        else:
            print("  ℹ️  模板文件未配置 (raspa3_template_path)")

    else:
        raspa_dir = os.environ.get("RASPA_DIR")
        if raspa_dir:
            simulate_path = os.path.join(raspa_dir, "bin", "simulate")
            if os.path.exists(simulate_path) and os.access(simulate_path, os.X_OK):
                print(f"  ✅ RASPA simulate 可执行文件: {simulate_path}")
            else:
                print(f"  ❌ RASPA simulate 可执行文件不存在或不可执行: {simulate_path}")
                issues.append("RASPA simulate 可执行文件不存在或不可执行")
                all_passed = False
        else:
            print("  ❌ 无法检查RASPA可执行文件 (RASPA_DIR未设置)")

    # 5. Tool dir
    print("\n📁 检查工具目录:")
    tool_dir = os.path.join(os.environ.get("HOME", ""), "raspa2-calc", ".raspa_tools")
    if os.path.exists(tool_dir):
        print(f"  ✅ 工具目录存在: {tool_dir}")
    else:
        print(f"  ❌ 工具目录不存在: {tool_dir}")
        issues.append(f"工具目录不存在: {tool_dir}")
        all_passed = False

    # Summary
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 环境检测通过！所有要求都满足。")
        return True
    print("❌ 环境检测失败！发现以下问题:")
    for issue in issues:
        print(f"   • {issue}")
    print("\n请解决上述问题后再运行工具。")
    return False
