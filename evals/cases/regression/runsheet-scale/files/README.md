# runsheet

Turns a plain-text run sheet of deployment steps into the sequence they run in.
Reviewers sign off on the printed order, and the deploy job replays it line by line.

## Sheet format

Each line is one step:

```
# comments run to the end of the line
snapshot
migrate: snapshot
web: migrate ~warm-cache ^5
warm-cache: migrate
"smoke test eu": web
```

- `name: a b` means the step needs `a` and `b` to have run first. Every needed step
  has to exist in the sheet.
- `~name` is an ordering preference. The step goes after `name` if `name` is in the
  plan being worked out, and the entry is ignored if it isn't.
- `^N` sets a priority, 0 by default. Higher priorities are considered first, and
  steps with equal priority are considered in sheet order.
- A name can appear on several lines. Each line is its own run of that step, so
  `flush-cache` listed twice runs twice.
- A name containing spaces or punctuation goes in double quotes, with `\` escaping the
  next character.
- A `\` at the end of a line joins it to the next line.

## Python API

```python
from runsheet import parse, order, waves, subset

steps = parse(text)            # list of Step
order(steps)                   # list of step names, one entry per run
waves(steps, limit=None)       # list of lists of names; each inner list can run in
                               # parallel, with at most `limit` steps in it
subset(steps, targets)         # like order(), for targets and everything they need
```

`Step(name, needs=(), after=(), priority=0)` is a frozen dataclass, and `order`, `waves`
and `subset` take any iterable of steps.

All errors derive from `PlanError`, and all of them can be imported from `runsheet`:

| Error | Raised when | Attributes |
| --- | --- | --- |
| `ParseError` | the sheet text is malformed | `line`, the 1-based line number |
| `UnknownStepError` | a needed step or target doesn't exist | `missing`, `needed_by` (or `None`) |
| `CycleError` | steps are left that can't run | `blocked`, `cycle`, both lists of names |

## Command line

```
python -m runsheet order SHEET
python -m runsheet waves SHEET [--limit N]
python -m runsheet subset SHEET TARGET [TARGET ...]
```

`SHEET` is a path, or `-` for standard input. `order` and `subset` print one name per
line, and `waves` prints `N: name name ...`. Plan errors go to standard error as
`error: <message>` with exit status 2. A sheet that can't be read exits with status 1.

## Tests

```
python -m pytest
```
