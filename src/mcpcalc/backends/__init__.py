"""Swappable calculation backends. A backend has: name, blocking_ui, evaluate(expr) -> float, set_angle_mode(mode)."""
from __future__ import annotations

from .python_backend import FUNCTION_NAMES, EvalError, PythonBackend

__all__ = ["EvalError", "FUNCTION_NAMES", "PythonBackend", "get_backend"]


def get_backend(cfg: dict):
    name = str(cfg.get("backend", "python")).lower()
    angle = cfg.get("angle_mode", "deg")
    if name == "python":
        return PythonBackend(angle_mode=angle)
    if name in {"windows_calculator", "windows"}:
        from .windows_backend import WindowsBackend

        return WindowsBackend(angle_mode=angle)
    raise ValueError(f"unknown backend '{name}' (use 'python' or 'windows_calculator')")
