"""Windows backend logic tested WITHOUT Windows: the step compiler is checked against a fake Calculator.

The fake Calculator replays the compiled steps with the Windows Calculator's rules (a function button applies to the
number or ( ) group just entered) and the resulting expression must equal the independent Python evaluator.
"""
import ast
import re
import sys

import pytest

from mcpcalc.backends import PythonBackend, get_backend
from mcpcalc.backends import windows_ui as ui
from mcpcalc.backends.windows_backend import WindowsBackend

_TOKEN = re.compile(r"\d+(?:\.\d+)?|\^|[()+\-*/%]")


def _matching_open(atoms, end):
    depth = 0
    for i in range(end, -1, -1):
        if atoms[i] == ")":
            depth += 1
        elif atoms[i].endswith("("):
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError("unbalanced")


def _operand_start(atoms, end):
    return _matching_open(atoms, end) if atoms[end] == ")" else end


def fake_calculator(steps) -> str:
    atoms: list[str] = []
    for step in steps:
        kind = step[0]
        if kind == "keys":
            atoms += _TOKEN.findall(step[1])
        elif kind == "const":
            atoms.append(step[1])
        elif kind == "logy":
            atoms.append("§")
        elif kind == "fn":
            name = step[1]
            if name == "rand":
                atoms.append("rand()")
                continue
            prefix = "-(" if name == "negate" else f"{name}("
            start = _operand_start(atoms, len(atoms) - 1)
            if atoms[start] == "(":
                atoms[start] = prefix
            elif atoms[start].endswith("("):
                atoms[start:start + 1] = [prefix, atoms[start]]
                atoms.append(")")
            else:
                atoms[start:] = [prefix, *atoms[start:], ")"]
            if atoms[start] == prefix and atoms[-1] != ")":
                atoms.append(")")
    while "§" in atoms:  # x logy y -> log(x, y)
        i = atoms.index("§")
        left = _operand_start(atoms, i - 1)
        right_end = _matching_close(atoms, i + 1) if atoms[i + 1].endswith("(") else i + 1
        atoms[left:right_end + 1] = ["log(", *atoms[left:i], ",", *atoms[i + 1:right_end + 1], ")"]
    return "".join(atoms).replace("^", "**")


def _matching_close(atoms, start):
    depth = 0
    for i in range(start, len(atoms)):
        if atoms[i].endswith("("):
            depth += 1
        elif atoms[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError("unbalanced")


EXPRESSIONS = [
    "sin(30)+cos(60)", "5*sqrt(16)", "5*log(5,4)", "abs(-6)", "root(27,3)", "ceil(sqrt(50))",
    "(sqrt(81)+3^2)*log(1000)/factorial(3)", "pi*7^2", "2*ln(4)", "sin(30)^2+cos(30)^2", "log(8,2)+1",
    "-sqrt(16)", "sqrt(4+5)*2", "asin(0.5)+acos(0.5)", "floor(7.9)+ceil(4.2)", "10*sin(60)", "recip(8)*square(3)",
    "factorial(5)/factorial(3)", "ln(e)", "2*(3+4)*5", "17%5+1", "cbrt(27)*4", "tanh(1)+sinh(1)",
]


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_compiled_key_sequence_reproduces_the_expression(expr):
    steps: list = []
    tree = ast.parse(expr.replace("^", "**"), mode="eval").body
    ui._compile(tree, steps)
    rebuilt = fake_calculator(steps)
    backend = PythonBackend()
    assert backend.evaluate(rebuilt.replace("**", "^")) == pytest.approx(backend.evaluate(expr), rel=1e-9), rebuilt


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_independent_verifier_matches_python_backend(expr):
    tree = ast.parse(expr.replace("^", "**"), mode="eval").body
    assert ui._py_eval(tree) == pytest.approx(PythonBackend().evaluate(expr), rel=1e-9)


def test_step_shapes():
    steps: list = []
    ui._compile(ast.parse("sin(30)+cos(60)", mode="eval").body, steps)
    assert steps == [("keys", "("), ("keys", "30"), ("fn", "sin"), ("keys", "+"), ("keys", "60"), ("fn", "cos"),
                     ("keys", ")")]


def test_unsupported_expression_is_rejected_by_the_compiler():
    with pytest.raises(ValueError):
        ui._compile(ast.parse("foo(3)", mode="eval").body, [])


def test_function_registry_covers_every_calculator_function():
    for name in ("sin", "asin", "sinh", "asinh", "sech", "acoth", "floor", "ceil", "rand", "square", "cube",
                 "cbrt", "factorial", "ln", "log", "exp", "power10", "power2", "abs", "recip", "negate"):
        assert name in ui._FUNCS, name


def test_windows_backend_refuses_to_start_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")  # pretend, so this test passes on every OS
    with pytest.raises(RuntimeError, match="only works on Windows"):
        WindowsBackend()


def test_windows_backend_can_be_created_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")  # construction does not touch the UI
    backend = WindowsBackend(angle_mode="rad")
    assert backend.name == "windows_calculator" and backend.blocking_ui is True
    assert "sin" in backend.functions()


def test_backend_factory():
    assert get_backend({"backend": "python"}).name == "python"
    with pytest.raises(ValueError):
        get_backend({"backend": "calculator-9000"})