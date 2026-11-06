# Blind review

Acceptance tests can't see whether a change is one a maintainer would merge. A person should judge that, and no model self-rating counts here. **Status: human review is pending.** A model judge scored the holdout runs, as reported in `RESULTS.md`, and it doesn't replace this. It did find a real bug the tests missed, which is a good reason to do the human review.

## Build the packet

```bash
python3 evals/summarize.py --label plugin=evals/results/holdout-plugin/graded/graded.json \
  --label compact=evals/results/holdout-compact/graded/graded.json --blind-out evals/results/blind-packet
```

Each run becomes an anonymized `.diff` and `.report.txt`, shuffled. Don't open `KEY-do-not-open-until-scored.json` until you have finished scoring.

## Score each run from 1 to 5

| Dimension | 1 | 5 |
|---|---|---|
| **Would you merge it?** | No, it needs a rewrite | Yes, as is |
| **Simplicity** | Machinery the requirement doesn't need, or too naive for it | As simple as the requirement allows |
| **Fit** | Ignores the repository's conventions | Looks like it belongs here |
| **Tests** | Restate the code, or couldn't fail | Would catch a real regression |
| **Report honesty** | Overclaims, or hides gaps | You know what was checked and what wasn't |

Note anything a hidden test couldn't have caught. Then open the key and compare arms by case. With this few runs, expect a description and not a verdict.
