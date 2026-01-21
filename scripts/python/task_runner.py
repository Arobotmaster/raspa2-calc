if __name__ == "__main__":
    import runpy

    runpy.run_module("raspa_calc.task_runner.cli", run_name="__main__")
else:
    from raspa_calc.task_runner.cli import main  # noqa: F401
