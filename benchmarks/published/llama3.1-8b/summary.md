# Benchmark results

## Accuracy (95% Wilson interval) and error taxonomy

| model | strategy | n | accuracy | 95% CI | wrong answer | not calc | blocked | exec error | retries | LLM ms |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.1:8b | baseline | 280 | 87.5% | 83.1%-90.9% | 7.9% | 0.0% | 4.6% | 0.0% | 0.00 | 3155 |
| llama3.1:8b | full | 280 | 92.9% | 89.2%-95.3% | 5.4% | 0.0% | 1.8% | 0.0% | 0.00 | 3000 |
| llama3.1:8b | prompt | 280 | 92.5% | 88.8%-95.0% | 5.4% | 0.0% | 2.1% | 0.0% | 0.00 | 6515 |
| llama3.1:8b | rewrite | 280 | 92.5% | 88.8%-95.0% | 5.4% | 0.0% | 2.1% | 0.0% | 0.00 | 5321 |

## Accuracy by difficulty

| model | strategy | easy | medium | hard | advanced |
|---|---|---|---|---|---|
| llama3.1:8b | baseline | 100.0% | 100.0% | 70.0% | 82.5% |
| llama3.1:8b | full | 100.0% | 95.7% | 84.3% | 92.5% |
| llama3.1:8b | prompt | 100.0% | 94.3% | 84.3% | 92.5% |
| llama3.1:8b | rewrite | 100.0% | 94.3% | 84.3% | 92.5% |
