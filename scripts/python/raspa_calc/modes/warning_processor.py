import sys


def run_warning_processor():
    """Run warning processor."""
    print("\n=== 警告处理模式 ===")
    print("该功能将分析CSV文件中的警告信息，并创建独立的警告任务")

    try:
        from ..tools.warning_processor import main as warning_main
        warning_main()
    except ImportError as e:
        print(f"错误: 无法导入警告处理模块: {e}")
        print("请确保warning_processor.py文件在scripts/python目录中")
        sys.exit(1)
    except Exception as e:
        print(f"警告处理过程中出错: {e}")
        sys.exit(1)
