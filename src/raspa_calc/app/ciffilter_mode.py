import sys


def run_ciffilter_tool():
    """Run CSV/CIF filter mode."""
    print("\n=== CSV/CIF 筛选模式 ===")
    print("该功能按条件/refcode筛选CSV并可选择复制对应的CIF文件")

    try:
        from .ciffilter import MOFFilterTool

        tool = MOFFilterTool()
        tool.run()
    except KeyboardInterrupt:
        print("\n⚠️  用户取消操作")
        sys.exit(130)
    except Exception as e:
        print(f"❌ CSV/CIF 筛选过程中出错: {e}")
        sys.exit(1)
