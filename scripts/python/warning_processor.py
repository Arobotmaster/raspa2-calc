#!/usr/bin/env python3

if __name__ == "__main__":
    import runpy

    runpy.run_module("raspa_calc.tools.warning_processor", run_name="__main__")
else:
    import importlib as _importlib

    _impl = _importlib.import_module("raspa_calc.tools.warning_processor")
    globals().update({
        key: value
        for key, value in _impl.__dict__.items()
        if not key.startswith("__")
    })
    del _importlib, _impl
