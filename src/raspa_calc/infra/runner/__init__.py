from .scheduler import build_node_plan, get_slurm_cluster_resources, parse_node_priorities


def main():
    """Lazy import to avoid circular dependency with app.task_runner."""
    from raspa_calc.app.task_runner import main as _main

    return _main()

__all__ = [
    "main",
    "build_node_plan",
    "get_slurm_cluster_resources",
    "parse_node_priorities",
]
