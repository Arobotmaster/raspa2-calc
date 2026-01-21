"""Compatibility shim for task_runner package."""

import importlib as _importlib

_impl = _importlib.import_module("raspa_calc.task_runner")
globals().update({
    key: value
    for key, value in _impl.__dict__.items()
    if not key.startswith("__")
})
__path__ = _impl.__path__

del _importlib, _impl
