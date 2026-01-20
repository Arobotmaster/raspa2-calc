import os
import sys


def run_ciffilter_tool():
    """Run CSV/CIF filter mode."""
    print("\n=== CSV/CIF 筛选模式 ===")
    print("该功能按条件/refcode筛选CSV并可选择复制对应的CIF文件")

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        tool_dir = os.path.abspath(os.path.join(script_dir, "..", "..", "..", ".."))
        default_tool_dir = os.path.join(os.environ.get("HOME", ""), "raspa2-calc", ".raspa_tools")

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
