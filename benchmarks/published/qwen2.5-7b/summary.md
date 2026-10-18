# Benchmark results

## Accuracy (95% Wilson interval) and error taxonomy

| model | strategy | n | accuracy | 95% CI | wrong answer | not calc | blocked | exec error | retries | LLM ms |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:7b | baseline | 280 | 92.5% | 88.8%-95.0% | 3.2% | 2.1% | 1.4% | 0.7% | 0.00 | 3664 |
| qwen2.5:7b | full | 280 | 99.3% | 97.4%-99.8% | 0.0% | 0.7% | 0.0% | 0.0% | 0.01 | 3151 |
| qwen2.5:7b | prompt | 280 | 98.2% | 95.9%-99.2% | 0.0% | 0.7% | 1.1% | 0.0% | 0.00 | 4164 |
| qwen2.5:7b | rewrite | 280 | 98.2% | 95.9%-99.2% | 0.0% | 0.7% | 1.1% | 0.0% | 0.00 | 3356 |

## Accuracy by difficulty

| model | strategy | easy | medium | hard | advanced |
|---|---|---|---|---|---|
| qwen2.5:7b | baseline | 100.0% | 100.0% | 78.6% | 92.5% |
| qwen2.5:7b | full | 96.7% | 100.0% | 100.0% | 100.0% |
| qwen2.5:7b | prompt | 96.7% | 97.1% | 98.6% | 100.0% |
| qwen2.5:7b | rewrite | 96.7% | 97.1% | 98.6% | 100.0% |
