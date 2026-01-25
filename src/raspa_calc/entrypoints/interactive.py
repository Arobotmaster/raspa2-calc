import sys

from raspa_calc.runtime import config as config_module
from raspa_calc.runtime import diagnostics
from raspa_calc.entrypoints import menu
from raspa_calc.app import (
    parameter_screening_mode as parameter_screening_cmd,
    ciffilter_mode as ciffilter_cmd,
    data_extractor_mode as data_extractor_cmd,
    isotherm_plotter_mode as isotherm_plotter_cmd,
    high_throughput as high_throughput_cmd,
    warning_processor_mode as warning_processor_cmd,
)


def _print_help() -> None:
    print("RASPA main interactive entry")
    print("Usage: raspa-calc")
    print("Options:")
    print("  -h, --help    show help and exit")
    print("  -v, --version show version and exit")
    print("  --no-check    skip environment check")


def main():
    """RASPA calculation CLI entry."""
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        _print_help()
        return 0

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ["-v", "--version"]:
            menu.show_version()
            return 0
        if arg == "--no-check":
            skip_check = True
        else:
            print(f"错误: 未知参数 '{arg}'")
            print("使用 'raspa-calc -h' 查看帮助")
            sys.exit(1)
    else:
        skip_check = False

    print("Welcome to RASPA Calculation System")

    config_module.load_runtime_config()

    if not diagnostics.check_disk_space():
        sys.exit(1)

    if not skip_check and not diagnostics.check_environment():
        print("\n💡 建议解决方案:")
        print("   1. 安装Python依赖: pip install gemmi numpy pandas")
        print("   2. 设置环境变量: export RASPA_DIR=/path/to/raspa")
        print("   3. 确保RASPA可执行文件存在且可执行")
        print("   4. 运行install.sh安装工具")
        sys.exit(1)

    raspa_version = config_module.get_raspa_version()
    print(f"\n🚀 当前版本: {config_module.__version__} ({config_module.__version_name__})")
    print(f"   • 当前 RASPA 版本: {raspa_version.upper()}")
    print("   • 支持 RASPA2/RASPA3 双版本切换")
    print("   • 支持多节点集群(NFS共享存储实现跨节点调度)")
    print("   • 配置参数化(支持从配置文件读取所有参数)")
    print("   • 集成gemmi库进行专业CIF处理")

    print(f"\n=== RASPA计算模式选择 ({raspa_version.upper()}) ===")
    print("1. 参数筛选模式（小批量运算）")
    print("2. 高通量计算模式（大规模计算）")
    print("3. 数据提取模式（从计算结果中提取数据）")
    print("4. 警告处理模式（处理计算中的警告任务）")
    print("5. 等温线绘制模式（批量绘制MOF等温吸附曲线）")
    print("6. CSV/CIF 筛选模式（MOF筛选器）")
    print()
    print("💡 切换 RASPA 版本: 修改 config.yaml 中的 raspa_version 配置项")

    try:
        choice = input("请选择运行模式 (1/2/3/4/5/6): ").strip()

        if choice == "1":
            parameter_screening_cmd.run_parameter_screening()
        elif choice == "2":
            high_throughput_cmd.run_high_throughput()
        elif choice == "3":
            data_extractor_cmd.run_data_extractor()
        elif choice == "4":
            warning_processor_cmd.run_warning_processor()
        elif choice == "5":
            isotherm_plotter_cmd.run_isotherm_plotter()
        elif choice == "6":
            ciffilter_cmd.run_ciffilter_tool()
        else:
            print("无效的选择，请输入1、2、3、4、5或6")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n用户取消操作")
        sys.exit(130)
    except Exception as e:
        print(f"发生错误: {str(e)}")
        sys.exit(1)
