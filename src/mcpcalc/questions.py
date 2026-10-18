"""Benchmark question generator.

Every question is written from a template together with its *reference expression*; the expected answer is computed
by the independent PythonBackend. Questions are generated with a fixed seed, so the dataset is reproducible:

    python -m mcpcalc.questions --out benchmarks/questions.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from .backends.python_backend import PythonBackend

ITEMS = ["pencils", "apples", "books", "candies", "pens", "eggs", "stickers", "marbles", "cookies", "balloons"]
QUOTAS = {"easy": 60, "medium": 70, "hard": 70, "advanced": 80}


def _item(r):
    return r.choice(ITEMS)


# ------------------------------------------------------------------ easy: one operation
def e_add(r):
    a, b = r.randint(10, 99), r.randint(10, 99)
    return f"I have {a} {_item(r)} and buy {b} more, how many do I have in total?", f"{a}+{b}"


def e_sub(r):
    a = r.randint(50, 200)
    b = r.randint(10, a - 5)
    return f"A shop has {a} {_item(r)} and sells {b}, how many are left?", f"{a}-{b}"


def e_mul(r):
    a, b = r.randint(3, 20), r.randint(3, 20)
    return f"Each box holds {a} {_item(r)}, how many are in {b} boxes?", f"{a}*{b}"


def e_div(r):
    b = r.randint(2, 12)
    a = b * r.randint(2, 25)
    return f"Share {a} {_item(r)} equally among {b} children, how many does each child get?", f"{a}/{b}"


def e_price(r):
    n, p = r.randint(5, 40), r.randint(2, 25)
    return f"i have {n} {_item(r)} and each cost {p} how much i get if i sell all of them", f"{n}*{p}"


def e_direct(r):
    word, sym = r.choice([("plus", "+"), ("minus", "-"), ("times", "*"), ("divided by", "/")])
    b = r.randint(2, 12)
    a = b * r.randint(2, 15) if sym == "/" else r.randint(b, 60)
    return f"what is {a} {word} {b}", f"{a}{sym}{b}"


# ------------------------------------------------------------------ medium: several steps
def m_bill(r):
    a, p, b, q = r.randint(2, 12), r.randint(5, 30), r.randint(2, 8), r.randint(40, 250)
    return f"I buy {a} pens at {p} each and {b} books at {q} each, what is the total bill?", f"{a}*{p}+{b}*{q}"


def m_change(r):
    a, p = r.randint(2, 9), r.randint(20, 90)
    paid = ((a * p) // 100 + 1) * 100 + r.choice([0, 100])
    return f"I buy {a} notebooks at {p} each and pay with {paid}, how much change do I get?", f"{paid}-{a}*{p}"


def m_area(r):
    length, w = r.randint(3, 30) + r.choice([0, 0.5]), r.randint(2, 20)
    return f"A rectangle is {length} long and {w} wide, what is its area?", f"{length}*{w}"


def m_perimeter(r):
    length, w = r.randint(3, 30), r.randint(2, 20)
    return f"A rectangle is {length} long and {w} wide, what is its perimeter?", f"2*({length}+{w})"


def m_speed(r):
    s, t = r.choice([40, 50, 60, 80, 90]), r.choice([1.5, 2, 2.5, 3, 4])
    return f"A train travels at {s} km per hour for {t} hours, how far does it go?", f"{s}*{t}"


def m_percent(r):
    p, n = r.choice([5, 10, 12, 15, 20, 25, 30, 40]), r.randint(2, 40) * 50
    return f"What is {p} percent of {n}?", f"({p}/100)*{n}"


def m_discount(r):
    p, n = r.choice([10, 15, 20, 25, 30]), r.randint(4, 60) * 500
    return f"A phone costs {n} and has a {p} percent discount, what is the final price?", f"{n}-({p}/100)*{n}"


def m_average(r):
    a, b, c = (r.randint(40, 100) for _ in range(3))
    return f"The marks are {a}, {b} and {c}, what is the average?", f"({a}+{b}+{c})/3"


def m_mod(r):
    b = r.randint(3, 12)
    a = r.randint(20, 200)
    return f"What is the remainder when {a} is divided by {b}?", f"{a}%{b}"


# ------------------------------------------------------------------ hard: powers, roots, factorials, pi
def h_sqrt_sq(r):
    n, k = r.randint(3, 20), r.randint(2, 12)
    return f"square root of {n * n} plus {k} squared", f"sqrt({n * n})+{k}^2"


def h_hyp(r):
    a, b = r.choice([(3, 4), (5, 12), (8, 15), (7, 24), (6, 8), (9, 12), (20, 21)])
    return f"A right triangle has sides {a} and {b}, what is the hypotenuse?", f"sqrt({a}^2+{b}^2)"


def h_fact(r):
    a = r.randint(5, 9)
    b = r.randint(2, a - 1)
    return f"{a} factorial divided by {b} factorial", f"factorial({a})/factorial({b})"


def h_cbrt(r):
    n, k = r.randint(2, 9), r.randint(2, 9)
    return f"cube root of {n ** 3} times {k}", f"cbrt({n ** 3})*{k}"


def h_circle(r):
    rad = r.randint(2, 15)
    return f"A circle has radius {rad}, what is its area?", f"pi*{rad}^2"


def h_cylinder(r):
    rad, h = r.randint(2, 10), r.randint(3, 20)
    return f"A cylinder has radius {rad} and height {h}, what is its volume?", f"pi*{rad}^2*{h}"


def h_compound(r):
    p, rate, t = r.choice([5000, 10000, 20000, 50000]), r.choice([4, 5, 6, 8, 10]), r.randint(2, 5)
    return (f"I invest {p} at {rate} percent a year for {t} years with compound interest, "
            f"what is the final amount?"), f"{p}*(1+{rate}/100)^{t}"


def h_power(r):
    a, b = r.randint(2, 9), r.randint(2, 6)
    return f"{a} to the power of {b}", f"{a}^{b}"


def h_cubed(r):
    a, b = r.randint(2, 9), r.randint(1, 30)
    return f"{a} cubed minus {b}", f"{a}^3-{b}"


def h_brackets(r):
    a, b, d = r.randint(2, 20), r.randint(2, 20), r.randint(2, 15)
    c = d + r.randint(2, 15)
    return f"({a} plus {b}) times ({c} minus {d})", f"({a}+{b})*({c}-{d})"


# ------------------------------------------------------------------ advanced: trig, logs, floor/ceil, inverse
def a_trig(r):
    t, p = r.choice([0, 30, 45, 60, 90]), r.choice([0, 30, 45, 60, 90])
    return f"sin {t} plus cos {p}", f"sin({t})+cos({p})"


def a_ladder(r):
    length, ang = r.choice([5, 8, 10, 12, 15, 20]), r.choice([30, 45, 60])
    return f"A {length} m ladder leans at {ang} degrees, how high does it reach?", f"{length}*sin({ang})"


def a_logbase(r):
    b, k = r.choice([2, 3, 4, 5]), r.randint(2, 5)
    return f"log {b ** k} base {b}", f"log({b ** k},{b})"


def a_log10(r):
    k = r.randint(1, 6)
    return f"log of {10 ** k}", f"log({10 ** k})"


def _decimal(r, lo=1, hi=500):
    x = r.randint(lo * 10, hi * 10) / 10
    return x + 0.3 if float(x).is_integer() else x


def a_ceil(r):
    x = _decimal(r)
    return r.choice([f"ceiling of {x}", f"upper limit of {x}"]), f"ceil({x})"


def a_floor(r):
    x = _decimal(r)
    return r.choice([f"floor of {x}", f"lower limit of {x}"]), f"floor({x})"


def a_buses(r):
    n, s = r.randint(100, 400), r.choice([30, 40, 45, 50])
    return f"{n} students need buses with {s} seats each, how many buses are needed?", f"ceil({n}/{s})"


def a_invtrig(r):
    name, expr = r.choice([("inverse sine of 0.5", "asin(0.5)"), ("inverse sine of 1", "asin(1)"),
                           ("inverse cosine of 0.5", "acos(0.5)"), ("inverse cosine of 0", "acos(0)"),
                           ("inverse tangent of 1", "atan(1)")])
    return name, expr


def a_hyper(r):
    name, fn = r.choice([("hyperbolic sine", "sinh"), ("hyperbolic cosine", "cosh"), ("hyperbolic tangent", "tanh")])
    x = r.choice([0.5, 1, 2])
    return f"{name} of {x}", f"{fn}({x})"


def a_ln(r):
    x = r.choice([2, 5, 10, 20, 50, 100])
    return f"natural log of {x}", f"ln({x})"


def a_exp(r):
    k = r.randint(1, 4)
    return f"e to the power {k}", f"exp({k})"


def a_combo_log(r):
    a, b, k = r.randint(2, 9), r.choice([2, 3, 5]), r.randint(2, 4)
    return f"{a} times log {b ** k} base {b}", f"{a}*log({b ** k},{b})"


def a_ceil_sqrt(r):
    n = r.choice([10, 20, 30, 50, 70, 90])
    return f"ceiling of the square root of {n}", f"ceil(sqrt({n}))"


def a_abs(r):
    n, m = r.randint(2, 50), r.randint(2, 50)
    return f"absolute value of -{n} plus {m}", f"abs(-{n})+{m}"


def a_recip(r):
    n = r.choice([2, 4, 5, 8, 10, 16, 20, 25])
    return f"reciprocal of {n}", f"recip({n})"


def a_floorsum(r):
    x, y = _decimal(r, 1, 50), _decimal(r, 1, 50)
    return f"floor of {x} plus ceiling of {y}", f"floor({x})+ceil({y})"


TEMPLATES = {
    "easy": [e_add, e_sub, e_mul, e_div, e_price, e_direct],
    "medium": [m_bill, m_change, m_area, m_perimeter, m_speed, m_percent, m_discount, m_average, m_mod],
    "hard": [h_sqrt_sq, h_hyp, h_fact, h_cbrt, h_circle, h_cylinder, h_compound, h_power, h_cubed, h_brackets],
    "advanced": [a_trig, a_ladder, a_logbase, a_log10, a_ceil, a_floor, a_buses, a_invtrig, a_hyper, a_ln, a_exp,
                 a_combo_log, a_ceil_sqrt, a_abs, a_recip, a_floorsum],
}


def generate(seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    reference = PythonBackend()
    rows, seen = [], set()
    for difficulty, quota in QUOTAS.items():
        templates, made, attempts = TEMPLATES[difficulty], 0, 0
        while made < quota and attempts < quota * 50:
            template = templates[attempts % len(templates)]  # round-robin keeps categories balanced
            attempts += 1
            question, expression = template(rng)
            if question in seen:
                continue
            seen.add(question)
            rows.append({"difficulty": difficulty, "category": template.__name__.split("_", 1)[1],
                         "question": question, "reference_expression": expression,
                         "expected": reference.evaluate(expression)})
            made += 1
    for i, row in enumerate(rows, start=1):
        row["id"] = f"q{i:03d}"
    return [{"id": r["id"], **{k: v for k, v in r.items() if k != "id"}} for r in rows]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate the benchmark question set")
    parser.add_argument("--out", default="benchmarks/questions.jsonl")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    rows = generate(args.seed)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    counts = {d: sum(1 for r in rows if r["difficulty"] == d) for d in QUOTAS}
    print(f"wrote {len(rows)} questions to {path}  {counts}")


if __name__ == "__main__":
    main()
