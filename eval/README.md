# Habit accuracy eval

```bash
python eval/run_eval.py
```

`samples.jsonl` — 79 labelled commands (`must_never_learn` / `safe_to_learn` / `safe_to_learn_exact`).

**Pass criteria:** zero dangerous promotes, zero cross-contamination (safe glob matching a dangerous command), all safe/exact samples promote after threshold.
