# Blind audit fixture

A plausible AI-generated "subscriptions and invoicing" service, written by a fresh subagent that was told nothing about occam's rules, with defects listed only in `ANSWERS.json` and correct-but-suspicious code in `DECOYS.json`. Its first run against the scanner, before anyone had read the key, is recorded in `docs/evaluation.md`. The key has since been read to improve the scanner, so this is now development data for the scanner, though it remains a fair test for an agent that can't see the key.

To audit it with an agent, copy `repo/` somewhere the agent can't see `ANSWERS.json` and `DECOYS.json`. `evals/score_audit.py` scores the scanner against the key, and it can score an agent's written report with `--report`.
