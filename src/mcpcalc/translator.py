"""English -> expression translation with four strategies (used as the ablation study in the benchmark).

baseline : minimal prompt
prompt   : full prompt with function list and worked examples
rewrite  : prompt + deterministic phrase rewrites ("5 squared" -> "(5^2)") before the LLM sees the text
full     : rewrite + validation with feedback and retry when the LLM invents a function or breaks the syntax
"""
from __future__ import annotations

import ast
import json
import re
import time
from dataclasses import dataclass

from .backends.python_backend import CONSTANTS, FUNCTION_NAMES

SCHEMA = {
    "type": "object",
    "properties": {"is_calculation": {"type": "boolean"}, "expression": {"type": "string"}},
    "required": ["is_calculation", "expression"],
}

MINIMAL_PROMPT = (
    "Convert the user's message into one math expression. Return JSON with is_calculation (boolean) and "
    "expression (string). Use + - * / ^ and functions like sqrt(x) or sin(x). Do not solve it."
)

FULL_PROMPT = (
    "You convert the user's message into ONE math expression. Return JSON only. Never solve it yourself. "
    "Keep every number from the message. Parts already written like sqrt(144) or (5^2) must be copied unchanged. "
    "Words: plus +, minus -, times/multiplied by *, divided by /, mod %, squared ^2, cubed ^3, "
    "'to the power of' ^. Functions you may use: sqrt cbrt abs factorial ln log log(x,base) root(x,y) "
    "floor ceil rand sin cos tan asin acos atan sinh cosh tanh exp(x) [e^x]. "
    "'upper limit' or 'ceiling' -> ceil ; 'lower limit' or 'floor' -> floor. "
    "Angles for sin/cos/tan are already in degrees: write sin(60). NEVER convert the angle and NEVER invent "
    "functions such as deg(), rad() or dms(). Use only the functions listed. "
    "Examples: "
    "'square root of 144 plus 5 squared' -> sqrt(144)+(5^2) ; "
    "'7 cubed minus 3' -> (7^3)-3 ; "
    "'i have 10 pencils each cost 5, total' -> 10*5 ; "
    "'log 5 base 4' -> log(5,4) ; "
    "'94 times log 5 base 7' -> 94*log(5,7) ; "
    "'sin 90' -> sin(90) ; "
    "'a 10 m ladder leans at 60 degrees, how high does it reach' -> 10*sin(60) ; "
    "'cos of 45 degrees' -> cos(45) ; "
    "'inverse sine of 0.5' -> asin(0.5) ; "
    "'ceiling of 4.2' -> ceil(4.2) ; "
    "'lower limit of 7.9' -> floor(7.9) ; "
    "'20 percent of 450' -> (20/100)*450 ; "
    "'5 factorial divided by 3 factorial' -> factorial(5)/factorial(3) ; "
    "'cube root of 27 times 4' -> cbrt(27)*4 ; "
    "'e to the power 2' -> exp(2) ; "
    "'17 mod 5' -> 17%5. "
    'For ordinary chat with no calculation, set is_calculation to false and expression to "".'
)

STRATEGIES = {
    "baseline": {"prompt": "minimal", "rewrite": False, "retry": False},
    "prompt": {"prompt": "full", "rewrite": False, "retry": False},
    "rewrite": {"prompt": "full", "rewrite": True, "retry": False},
    "full": {"prompt": "full", "rewrite": True, "retry": True},
}

_NUM = r"(\d+(?:\.\d+)?)"
RULES = [
    (rf"square\s+root\s+of\s+{_NUM}", r"sqrt(\1)"),
    (rf"cube\s+root\s+of\s+{_NUM}", r"cbrt(\1)"),
    (rf"{_NUM}\s+(?:squared|square)\b(?!\s+root)", r"(\1^2)"),
    (rf"{_NUM}\s+cubed\b", r"(\1^3)"),
    (rf"{_NUM}\s+factorial\b", r"factorial(\1)"),
]

ALLOWED_NAMES = frozenset(FUNCTION_NAMES) | frozenset(CONSTANTS)

_MATH_HINT = re.compile(
    r"\d|\b(?:plus|minus|times|multiply|divide|divided|over|power|percent|mod|root|sqrt|square|cube|log|ln|"
    r"sin|cos|tan|factorial|floor|ceil|ceiling|limit|reciprocal|absolute)\b|[+\-*/^()]", re.IGNORECASE)


def normalize(text: str) -> str:
    for pattern, replacement in RULES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def looks_like_math(text: str) -> bool:
    return bool(_MATH_HINT.search(text))


def check_expression(expression: str) -> str | None:
    """Return a problem description, or None if the expression looks valid."""
    try:
        tree = ast.parse(expression.replace("^", "**"), mode="eval")
    except SyntaxError as ex:
        return f"syntax error ({ex.msg})"
    bad = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id.lower() not in ALLOWED_NAMES})
    return f"unsupported names: {', '.join(bad)}" if bad else None


@dataclass
class Translation:
    is_calculation: bool
    expression: str
    normalized: str
    retries: int
    llm_ms: float
    raw: str = ""
    error: str = ""


async def translate(llm, text: str, strategy: str = "full", max_retries: int = 2) -> Translation:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy '{strategy}' (choose from {', '.join(STRATEGIES)})")
    opts = STRATEGIES[strategy]
    prompt = FULL_PROMPT if opts["prompt"] == "full" else MINIMAL_PROMPT
    normalized = normalize(text) if opts["rewrite"] else text
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": normalized}]
    attempts = 1 + (max_retries if opts["retry"] else 0)

    started = time.perf_counter()
    retries, raw, plan, problem = 0, "", None, None
    for attempt in range(attempts):
        raw = await llm.chat_json(messages, SCHEMA)
        try:
            plan = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            plan = None
        problem = None
        if not isinstance(plan, dict):
            problem = "Return valid JSON with is_calculation and expression."
        elif plan.get("is_calculation") and str(plan.get("expression") or "").strip():
            issue = check_expression(str(plan["expression"]))
            if issue:
                problem = (f"Your expression has a problem: {issue}. Use only the allowed functions. "
                           "Angles are already in degrees: write sin(60), never deg(60).")
        if problem is None or attempt == attempts - 1:
            break
        retries += 1
        messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": problem}]

    llm_ms = (time.perf_counter() - started) * 1000
    if not isinstance(plan, dict):
        return Translation(False, "", normalized, retries, llm_ms, raw, "invalid JSON from the model")
    expression = str(plan.get("expression") or "").strip()
    return Translation(bool(plan.get("is_calculation")) and bool(expression), expression, normalized, retries,
                       llm_ms, raw, problem or "")
