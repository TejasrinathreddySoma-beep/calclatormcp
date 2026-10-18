"""Safety policy: syntax whitelist, function allowlist, size limits and dry-run."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .backends.python_backend import CONSTANTS, FUNCTION_NAMES


class SafetyError(ValueError):
    """The expression was rejected by the policy (it is never executed)."""


_ALLOWED_NODES = (ast.Expression, ast.Constant, ast.Name, ast.UnaryOp, ast.BinOp, ast.Call, ast.Load,
                  ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.UAdd, ast.USub)


@dataclass
class Policy:
    allowed_functions: frozenset = field(default_factory=lambda: FUNCTION_NAMES)
    max_length: int = 200
    max_nodes: int = 120
    dry_run: bool = False


def policy_from_config(cfg: dict) -> Policy:
    s = cfg.get("safety", {})
    allowed = s.get("allowed_functions", "all")
    funcs = FUNCTION_NAMES if allowed == "all" else frozenset(str(f).lower() for f in allowed)
    return Policy(funcs, int(s.get("max_expression_length", 200)), int(s.get("max_nodes", 120)),
                  bool(s.get("dry_run", False)))


def validate(expression: str, policy: Policy) -> list[str]:
    """Return the function names used, or raise SafetyError."""
    text = (expression or "").strip()
    if not text:
        raise SafetyError("empty expression")
    if len(text) > policy.max_length:
        raise SafetyError(f"expression longer than {policy.max_length} characters")
    try:
        tree = ast.parse(text.replace("^", "**"), mode="eval")
    except SyntaxError as ex:
        raise SafetyError(f"syntax error: {ex.msg}") from None

    func_nodes = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    used: set[str] = set()
    for count, node in enumerate(ast.walk(tree), start=1):
        if count > policy.max_nodes:
            raise SafetyError("expression too complex")
        if not isinstance(node, _ALLOWED_NODES):
            raise SafetyError(f"forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise SafetyError("only numbers are allowed")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise SafetyError("only plain function calls are allowed")
        if isinstance(node, ast.Name):
            name = node.id.lower()
            if id(node) in func_nodes:
                if name not in policy.allowed_functions:
                    raise SafetyError(f"function '{node.id}' is not allowed")
                used.add(name)
            elif name not in CONSTANTS:
                raise SafetyError(f"unknown name '{node.id}'")
    return sorted(used)
