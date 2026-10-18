import pytest

from mcpcalc.config import load_config
from mcpcalc.safety import Policy, SafetyError, policy_from_config, validate


def test_returns_used_functions(policy):
    assert validate("sqrt(144)+sin(30)*pi", policy) == ["sin", "sqrt"]
    assert validate("1+2", policy) == []


@pytest.mark.parametrize("expr", [
    "__import__('os').system('x')", "open('f')", "(1).real", "math.sin(1)", "abs.__class__", "[1][0]", "{1: 2}",
    "lambda: 1", "'text'", "True", "None", "1 if 2 else 3", "sin(x=1)", "sin(*args)", "f(1)(2)", "a", "x+1",
    "", "   ", "2+", "1; 2", "x := 1", "1 < 2", "not 1", "1 and 2", "-(-(-x))",
])
def test_blocks_dangerous_or_invalid(policy, expr):
    with pytest.raises(SafetyError):
        validate(expr, policy)


def test_allowlist_blocks_other_functions():
    policy = Policy(allowed_functions=frozenset({"sqrt"}))
    assert validate("sqrt(4)", policy) == ["sqrt"]
    with pytest.raises(SafetyError, match="not allowed"):
        validate("sin(30)", policy)


def test_length_and_node_limits():
    with pytest.raises(SafetyError, match="longer"):
        validate("1+" * 150 + "1", Policy(max_length=200))
    with pytest.raises(SafetyError, match="complex"):
        validate("+".join(["1"] * 40), Policy(max_nodes=30))


def test_policy_from_config_list_and_defaults():
    cfg = load_config("does-not-exist.yaml")
    assert "sin" in policy_from_config(cfg).allowed_functions
    cfg["safety"].update(allowed_functions=["SQRT", "Log"], dry_run=True, max_expression_length=50)
    policy = policy_from_config(cfg)
    assert policy.allowed_functions == frozenset({"sqrt", "log"})
    assert policy.dry_run and policy.max_length == 50
