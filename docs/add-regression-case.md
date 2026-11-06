# Adding a failure seen in real use

When the skill, or an agent without it, fails in real work, turn that into a case. This is how the suite stays honest about what matters rather than what its author imagined.

1. **Write down the failure,** in terms of behavior: what was asked, what the agent did, and what went wrong. Check whether a scenario in `evals/scenarios.yaml` already covers it. Add one if not.
2. **Make the smallest repository that reproduces it** under `evals/cases/smoke/<case>/`, copying the layout of an existing case. Use synthetic data and `.invalid` domains, and never real credentials.
3. **Write the prompt as a person would have typed it.** Don't state the diagnosis. Add case-specific terms to the leak list in `tests/test_scenarios.py`.
4. **Write hidden checks** in `hidden/test_*.py` that use only entry points the prompt fixes, so a different valid design doesn't fail.
5. **Add solutions:** `solutions/reference/`, plus a `solutions/trap-<name>/` reproducing the failure you saw, with an `EXPECT_FAIL` file. If the case assumes a visible test state, record it in `hidden/visible_state.json`.
6. **Calibrate:** `python3 -m pytest tests/test_calibration.py -q -k <case>`. The starter and trap must fail, and the reference must pass.
7. **Record the change, and log why:** run `python3 evals/freeze.py write` and add a line to the changes section of `evals/PREREGISTRATION.md`. Existing runs of other cases stay valid. Runs of a changed case don't.
8. **Pilot it without the skill.** If an unaided agent clears it every time, label it a regression guard rather than evidence of benefit.
9. **Only then consider changing the skill.** Generalize from the failure rather than adding its specifics, and check `tests/test_scenarios.py` still passes. Don't weaken permission boundaries or acceptance tests to make a case pass.

Re-run the comparison when a new model arrives. A rule that stops making a difference should be removed.
