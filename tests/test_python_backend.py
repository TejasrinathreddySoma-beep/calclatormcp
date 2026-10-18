import math
import random

import pytest

from mcpcalc.backends.python_backend import FUNCTION_NAMES, EvalError, PythonBackend


@pytest.mark.parametrize("expr,expected", [
    ("2+3*4", 14), ("(2+3)*4", 20), ("2^3", 8), ("2^3^2", 512), ("10/4", 2.5), ("17%5", 2), ("-3+5", 2),
    ("--4", 4), ("sqrt(144)+5^2", 37), ("sqrt(144)+(5^2)", 37), ("5*6", 30), ("1.5*4", 6),
    ("sin(30)+cos(60)", 1), ("sin(90)", 1), ("cos(90)", 0), ("tan(45)", 1), ("sin(180)", 0),
    ("asin(0.5)", 30), ("acos(0.5)", 60), ("atan(1)", 45),
    ("sinh(1)", math.sinh(1)), ("cosh(2)", math.cosh(2)), ("asinh(1)", math.asinh(1)),
    ("sec(60)", 2), ("csc(30)", 2), ("cot(45)", 1),
    ("log(1000)", 3), ("log(8,2)", 3), ("log(81,3)", 4), ("log(1000,10)", 3), ("ln(e)", 1),
    ("5*log(5,4)", 5 * math.log(5) / math.log(4)), ("log10(100)", 2),
    ("exp(2)", math.exp(2)), ("power10(3)", 1000), ("power2(5)", 32),
    ("floor(7.9)", 7), ("ceil(4.2)", 5), ("ceiling(4.2)", 5), ("ceil(sqrt(50))", 8),
    ("factorial(5)", 120), ("factorial(0)", 1), ("factorial(5)/factorial(3)", 20),
    ("cbrt(27)", 3), ("cbrt(64)", 4), ("cbrt(-8)", -2), ("root(27,3)", 3), ("root(16,4)", 2),
    ("abs(-6)", 6), ("recip(8)", 0.125), ("reciprocal(4)", 0.25), ("square(9)", 81), ("cube(3)", 27),
    ("pi*7^2", math.pi * 49), ("pi", math.pi), ("E", math.e), ("SQRT(16)", 4),
    ("negate(5)", -5), ("to_dms(30.5)", 30.3), ("to_deg(30.3)", 30.5),
    ("(sqrt(81)+3^2)*log(1000)/factorial(3)", 9),
])
def test_values(backend, expr, expected):
    assert backend.evaluate(expr) == pytest.approx(expected, rel=1e-9, abs=1e-9)


def test_rand_is_in_unit_interval():
    backend = PythonBackend(seed=1)
    assert 0 <= backend.evaluate("rand()") < 1


def test_angle_modes():
    backend = PythonBackend()
    backend.set_angle_mode("rad")
    assert backend.evaluate("sin(pi/2)") == pytest.approx(1)
    assert backend.evaluate("asin(1)") == pytest.approx(math.pi / 2)
    backend.set_angle_mode("grad")
    assert backend.evaluate("sin(100)") == pytest.approx(1)
    assert backend.evaluate("asin(1)") == pytest.approx(100)
    backend.set_angle_mode("deg")
    assert backend.evaluate("sin(90)") == pytest.approx(1)
    with pytest.raises(EvalError):
        backend.set_angle_mode("turns")


@pytest.mark.parametrize("expr", [
    "1/0", "5%0", "0^-1", "sqrt(-1)", "log(0)", "log(-5)", "ln(0)", "log(5,1)", "factorial(171)", "factorial(-1)",
    "factorial(2.5)", "tan(90)", "cot(0)", "sec(90)", "asin(2)", "acosh(0.5)", "(-8)^0.5", "2^10001", "10^400",
    "9^9^9", "root(-4,2)", "root(4,0)", "recip(0)", "",  "   ", "2+", "((", "foo(3)", "sin()", "sin(1,2)", "xyz",
    "__import__('os').system('echo hi')", "(1).real", "'a'*3", "[1,2][0]", "lambda: 1", "1 if 2 else 3", "True",
    "sin(x=1)", "abs.__class__", "1;2", "x := 3", "1e999", "9" * 600,
])
def test_rejects(backend, expr):
    with pytest.raises(EvalError):
        backend.evaluate(expr)


def test_deep_nesting_is_rejected(backend):
    with pytest.raises(EvalError, match="nested"):
        backend.evaluate("abs(" * 60 + "1" + ")" * 60)
    assert backend.evaluate("(" * 60 + "1" + ")" * 60) == 1  # plain brackets add no nesting


def test_random_arithmetic_matches_python(backend):
    """Property test: for + - * on small ints the evaluator must agree with Python itself."""
    rng = random.Random(0)

    def build(depth):
        if depth == 0 or rng.random() < 0.25:
            return str(rng.randint(0, 20))
        return f"({build(depth - 1)} {rng.choice('+-*')} {build(depth - 1)})"

    for _ in range(300):
        expr = build(4)
        assert backend.evaluate(expr) == pytest.approx(eval(expr))  # noqa: S307 - trusted generated input


def test_function_table_is_complete(backend):
    for name in ("sin", "asinh", "factorial", "log", "root", "rand", "floor", "ceil", "cbrt"):
        assert name in FUNCTION_NAMES
    assert backend.functions() == sorted(backend.functions())
