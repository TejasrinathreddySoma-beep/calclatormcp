# Benchmark data

`questions.jsonl` holds 280 questions, one JSON object per line:

| field | meaning |
|---|---|
| `id` | `q001` ... `q280` |
| `difficulty` | `easy` (60), `medium` (70), `hard` (70), `advanced` (80) |
| `category` | the template the question came from (`bill`, `hyp`, `ladder`, `logbase`, ...) |
| `question` | the English text given to the LLM |
| `reference_expression` | a human-written correct expression for the question |
| `expected` | the answer, computed from the reference expression by the independent `PythonBackend` |

The file is reproducible: `python -m mcpcalc.questions --seed 42` regenerates it byte for byte, and a test fails
if the committed file and the generator ever disagree.

## Scoring

A run is **correct** when the LLM's expression is accepted by the safety policy and evaluates to `expected`
(relative tolerance 1e-6). Failures are classified, so the report can say *why* a strategy helps:

| outcome | meaning |
|---|---|
| `wrong_answer` | a valid expression was executed but gave the wrong number (the LLM misread the question) |
| `blocked` | the expression used an invented function or forbidden syntax (e.g. `deg(60)`) |
| `not_calculation` | the LLM treated the question as chat |
| `exec_error` | valid syntax but a maths error (division by zero, domain error) |

## Known limitations of the dataset

* Questions come from templates, so phrasing variety is limited (some categories, such as inverse trig, have only a
  few distinct wordings). Add hand-written questions to `questions.jsonl` for a more realistic test.
* Answers use degrees for trig functions and base 10 for `log`, matching the Windows Calculator.
* Word problems are unambiguous by construction; real users are messier.
