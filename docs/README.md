# Occam docs

None of this is loaded during coding sessions.

## Using occam

| Read | When you want to know |
|---|---|
| [Examples](examples.md) | What occam does in practice, and what good output looks like |
| [The `occam` CLI](tools.md) | What each command does, and how to read findings |
| [Claude Code integration](claude-code.md) | What each hook does, how firmly, and what it can't do |
| [Codex adapter](../adapters/codex/README.md) | How to install on Codex. Nothing there has been run |

## Deciding whether to trust it

| Read | When you want to know |
|---|---|
| [What was tested](evidence.md) | The results, and the status of each combination |
| [Evaluating audit and repair](evaluation.md) | How the audit skill and scanner performed, and what independent reviews found |
| [How agents get code wrong](failure-modes.md) | Ten failure modes, what occam does about each, and what still gets past it |
| [Full results](../evals/RESULTS.md) | Every table and caveat, and what the evaluation cost |

## Working on occam

| Read | When you want to know |
|---|---|
| [Evaluation suite](../evals/README.md) | How to run the checks and the billed agent comparisons |
| [Adding a failure seen in real use](add-regression-case.md) | How to turn a real failure into a test case |
| [Coverage map](coverage-map.md) | Which mechanism and test covers each concern |
| [Design](../DESIGN.md) | What's decided about occam itself and why. Read the slice you need with `occam design for <path>` |
| [Research record](research.md) | The approaches this draws on, and the decision on each |

The Karpathy-inspired guidelines credited in the research record are maintained by their repository's authors. Karpathy did not write or endorse this project.

## Running the tests

These are free and deterministic. The full run took about 13 minutes when last timed.

```bash
pip install --group dev
python3 -m pytest tests/ -q
```

## Repository layout

| Path | Contents |
|---|---|
| `plugin/skills/occam/` | Core skill, its references, and the `occam` tools in `scripts/` |
| `plugin/skills/occam-audit/` | Auditing and repairing existing code, with references on repair, scale and reporting |
| `plugin/skills/occam-docs/` | Writing documentation from code, then handing the prose to human-voice |
| `plugin/skills/occam-*/` | Language skills: Python, TypeScript and JavaScript, Rust, Go, Java and Kotlin, C and C++, SQL, shell. Python is the primary target, and post-evaluation has its own references |
| `plugin/hooks/` | The enforcement hooks and their configuration, for Claude Code and Codex |
| `plugin/agents/` | The reviewer and auditor agents |
| `adapters/` | Codex material |
| `assets/` | Logo files |
| `docs/` | These docs |
| `evals/` | Scenarios, cases, grader, preregistration, results. Raw run output in `evals/results/` is generated and isn't in the repository |
| `tests/` | The free deterministic tests |
| `.github/` | CI: ruff and the free tests on Linux and macOS. Paid evals never run there |
