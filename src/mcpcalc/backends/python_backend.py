"""Safe, dependency-free expression evaluator.

It is the default backend and also the *independent reference* used to verify other backends.
Conventions match the Windows Calculator: trig uses degrees by default, ``log`` is base 10, ``ln`` is natural.
No ``eval``: the expression is parsed with ``ast`` and only whitelisted node types are executed.
"""
from __future__ import annotations

import ast
import math
import random

MAX_LENGTH = 500
MAX_DEPTH = 50
MAX_EXPONENT = 10_000

ALIASES = {"log10": "log", "ceiling": "ceil", "random": "rand", "reciprocal": "recip"}
CONSTANTS = {"pi": math.pi, "e": math.e}


class EvalError(ValueError):
    """Raised for any expression that cannot be evaluated."""


def _clean(value: float) -> float:
    return 0.0 if abs(value) < 1e-12 else value


def _cbrt(x: float) -> float:
    native = getattr(math, "cbrt", None)
    if native:
        return native(x)
    root = math.copysign(abs(x) ** (1 / 3), x)
    nearest = round(root)
    return float(nearest) if abs(nearest ** 3 - x) < 1e-9 * max(1.0, abs(x)) else root


def _factorial(x: float) -> float:
    if x < 0 or not float(x).is_integer() or x > 170:
        raise EvalError("factorial needs an integer between 0 and 170")
    return float(math.factorial(int(x)))


def _to_dms(x: float) -> float:
    degrees = int(x)
    rest = (x - degrees) * 60
    minutes = int(rest)
    seconds = (rest - minutes) * 60
    return degrees + minutes / 100 + seconds / 10000


def _from_dms(x: float) -> float:
    degrees = int(x)
    rest = (x - degrees) * 100
    minutes = int(rest)
    seconds = (rest - minutes) * 100
    return degrees + minutes / 60 + seconds / 3600


def _log_base(x: float, base: float) -> float:
    if x <= 0:
        raise EvalError("log needs a positive value")
    if base <= 0 or base == 1:
        raise EvalError("log base must be positive and not 1")
    value = math.log(x) / math.log(base)
    nearest = round(value)
    if abs(value - nearest) < 1e-12 and abs(base ** nearest - x) <= 1e-9 * abs(x):
        return float(nearest)  # exact results such as log(8, 2) = 3
    return value


def _root(x: float, y: float) -> float:
    if y == 0:
        raise EvalError("root degree cannot be zero")
    if x < 0 and float(y).is_integer() and int(y) % 2 == 1:
        return -((-x) ** (1 / y))
    if x < 0:
        raise EvalError("even root of a negative number")
    return x ** (1 / y)


class PythonBackend:
    name = "python"
    blocking_ui = False

    def __init__(self, angle_mode: str = "deg", seed: int | None = None):
        self.angle_mode = "deg"
        self.set_angle_mode(angle_mode)
        self._rng = random.Random(seed)
        self._unary = self._build_unary()

    # ------------------------------------------------------------------ angle handling
    def set_angle_mode(self, mode: str) -> str:
        short = mode.strip().lower()[:3]
        if short not in {"deg", "rad", "gra"}:
            raise EvalError("angle mode must be deg, rad or grad")
        self.angle_mode = "grad" if short == "gra" else short
        return f"Angle mode set to {self.angle_mode}."

    def _to_rad(self, v: float) -> float:
        return math.radians(v) if self.angle_mode == "deg" else (v * math.pi / 200 if self.angle_mode == "grad" else v)

    def _from_rad(self, r: float) -> float:
        return math.degrees(r) if self.angle_mode == "deg" else (r * 200 / math.pi if self.angle_mode == "grad" else r)

    # ------------------------------------------------------------------ function table
    def _build_unary(self) -> dict:
        rad, back = self._to_rad, self._from_rad

        def sin_cos(x):
            a = rad(x)
            return math.sin(a), math.cos(a)

        def tan(x):
            s, c = sin_cos(x)
            if abs(c) < 1e-12:
                raise EvalError("tan is undefined at this angle")
            return _clean(s / c)

        def cot(x):
            s, c = sin_cos(x)
            if abs(s) < 1e-12:
                raise EvalError("cot is undefined at this angle")
            return _clean(c / s)

        def sec(x):
            c = sin_cos(x)[1]
            if abs(c) < 1e-12:
                raise EvalError("sec is undefined at this angle")
            return 1 / c

        def csc(x):
            s = sin_cos(x)[0]
            if abs(s) < 1e-12:
                raise EvalError("csc is undefined at this angle")
            return 1 / s

        return {
            "sqrt": math.sqrt, "cbrt": _cbrt, "square": lambda x: x * x, "cube": lambda x: x ** 3,
            "recip": lambda x: 1 / x, "abs": abs, "factorial": _factorial, "negate": lambda x: -x,
            "ln": math.log, "log": math.log10, "power10": lambda x: 10.0 ** x, "power2": lambda x: 2.0 ** x,
            "exp": math.exp, "floor": lambda x: float(math.floor(x)), "ceil": lambda x: float(math.ceil(x)),
            "to_dms": _to_dms, "to_deg": _from_dms,
            "sin": lambda x: _clean(sin_cos(x)[0]), "cos": lambda x: _clean(sin_cos(x)[1]),
            "tan": tan, "cot": cot, "sec": sec, "csc": csc,
            "asin": lambda x: back(math.asin(x)), "acos": lambda x: back(math.acos(x)),
            "atan": lambda x: back(math.atan(x)), "asec": lambda x: back(math.acos(1 / x)),
            "acsc": lambda x: back(math.asin(1 / x)), "acot": lambda x: back(math.atan(1 / x)),
            "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
            "sech": lambda x: 1 / math.cosh(x), "csch": lambda x: 1 / math.sinh(x), "coth": lambda x: 1 / math.tanh(x),
            "asinh": math.asinh, "acosh": math.acosh, "atanh": math.atanh,
            "asech": lambda x: math.acosh(1 / x), "acsch": lambda x: math.asinh(1 / x),
            "acoth": lambda x: math.atanh(1 / x),
        }

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, expression: str) -> float:
        text = expression.strip().replace("^", "**")
        if not text:
            raise EvalError("empty expression")
        if len(text) > MAX_LENGTH:
            raise EvalError("expression too long")
        try:
            tree = ast.parse(text, mode="eval")
            value = self._eval(tree.body, 0)
        except SyntaxError as ex:
            raise EvalError(f"syntax error: {ex.msg}") from None
        except (OverflowError, ZeroDivisionError, ValueError) as ex:
            if isinstance(ex, EvalError):
                raise
            raise EvalError(f"math error: {ex}") from None
        if isinstance(value, complex) or not math.isfinite(value):
            raise EvalError("result is not a finite real number")
        return float(value)

    def _eval(self, node, depth: int) -> float:
        if depth > MAX_DEPTH:
            raise EvalError("expression nested too deeply")
        nxt = depth + 1
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise EvalError("only numbers are allowed")
            return float(node.value)
        if isinstance(node, ast.Name):
            name = node.id.lower()
            if name in CONSTANTS:
                return CONSTANTS[name]
            raise EvalError(f"unknown name '{node.id}'")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self._eval(node.operand, nxt)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            return self._binary(node, nxt)
        if isinstance(node, ast.Call):
            return self._call(node, nxt)
        raise EvalError(f"unsupported syntax: {type(node).__name__}")

    def _binary(self, node: ast.BinOp, depth: int) -> float:
        a, b = self._eval(node.left, depth), self._eval(node.right, depth)
        op = type(node.op)
        if op is ast.Add:
            return a + b
        if op is ast.Sub:
            return a - b
        if op is ast.Mult:
            return a * b
        if op in (ast.Div, ast.Mod):
            if b == 0:
                raise EvalError("division by zero")
            return a / b if op is ast.Div else a % b
        if op is ast.Pow:
            if a == 0 and b < 0:
                raise EvalError("0 cannot be raised to a negative power")
            if a < 0 and not float(b).is_integer():
                raise EvalError("result would be a complex number")
            if abs(b) > MAX_EXPONENT:
                raise EvalError("exponent too large")
            return a ** b
        raise EvalError(f"unsupported operator {op.__name__}")

    def _call(self, node: ast.Call, depth: int) -> float:
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise EvalError("only plain function calls are allowed")
        name = ALIASES.get(node.func.id.lower(), node.func.id.lower())
        args = [self._eval(a, depth) for a in node.args]
        if name == "rand" and not args:
            return self._rng.random()
        if name == "log" and len(args) == 2:
            return _log_base(args[0], args[1])
        if name == "root" and len(args) == 2:
            return _root(args[0], args[1])
        if name in self._unary and len(args) == 1:
            return self._unary[name](args[0])
        raise EvalError(f"unsupported function call {node.func.id}/{len(args)}")

    def functions(self) -> list[str]:
        return sorted(set(self._unary) | {"root", "rand"})


FUNCTION_NAMES = frozenset(PythonBackend().functions()) | frozenset(ALIASES)
