import re


def _parse_submit_index(line):
    match = re.search(r"正在提交(?:作业\s*|第)(\d+)", line)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _should_print_submit_line(line):
    important_markers = (
        "错误",
        "失败",
        "⚠️",
        "❌",
        "警告",
        "WARNING",
        "Error",
        "ERROR",
        "开始提交计算任务",
        "使用CPU核心数",
        "提交模式",
        "开始逐个提交作业",
        "job array",
        "Job array",
        "节点分配计划",
        "提交汇总",
        "所有作业已提交完成",
        "提示",
        "检测到",
    )
    return any(marker in line for marker in important_markers)
