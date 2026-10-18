"""Thin backend wrapper around the Windows Calculator UI layer (optional, Windows only)."""
from __future__ import annotations

import sys

from .python_backend import EvalError


class WindowsBackend:
    name = "windows_calculator"
    blocking_ui = True  # UI Automation (COM) must stay on one thread, so it runs inline, never in a thread pool

    def __init__(self, angle_mode: str = "deg"):
        if sys.platform != "win32":
            raise RuntimeError("the windows_calculator backend only works on Windows")
        from . import windows_ui

        self._ui = windows_ui
        self._angle = angle_mode
        self._angle_applied = False

    def set_angle_mode(self, mode: str) -> str:
        out = self._ui.windows_set_angle_mode(mode)
        if out.startswith("Error"):
            raise EvalError(out)
        self._angle_applied = True
        return out

    def evaluate(self, expression: str) -> float:
        if not self._angle_applied:
            self.set_angle_mode(self._angle)
        try:
            return float(self._ui.windows_evaluate(expression))
        except ValueError as ex:
            raise EvalError(str(ex)) from None

    def functions(self) -> list[str]:
        from .python_backend import PythonBackend

        return PythonBackend().functions()
