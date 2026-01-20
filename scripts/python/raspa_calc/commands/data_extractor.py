import sys


def run_data_extractor():
    """Run data extractor."""
    print("\n=== 数据提取模式 ===")
    print("该功能将从计算结果中提取关键数据并生成Excel表格")

    try:
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
