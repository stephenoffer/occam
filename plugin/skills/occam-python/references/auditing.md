# Auditing existing Python

occam-audit, if available, covers how to audit and repair any codebase, from one cell to a monorepo: scoping, triage, order of work and what may be fixed without asking. This covers what is particular to Python. Every result is a lead until you have confirmed the failure, and the core skill's verification reference covers how to write up findings.

## Keep the audit read-only

Python tools leave files behind. Use `PYTHONDONTWRITEBYTECODE=1`, `pytest -p no:cacheprovider`, `ruff check --no-cache`, `mypy --cache-dir=/dev/null`, and a `COVERAGE_FILE` outside the tree. Use `--check` or `--diff` with formatters, and leave `--fix` off. Don't install into the project's environment. `uvx` and `pipx run` keep a tool separate, but they still download and run code, so follow the repository's dependency policy.

Importing and collecting aren't read-only. `import pkg` and `pytest --collect-only` run module top levels and `conftest.py`, which can write files or do worse in code you haven't reviewed. Running the suite goes further, since tests can reach real services. Read those first, check what the configuration points at, or work on a copy.

## What to run

Use the tools the project already has before adding others, and use each one's own configuration first.

| Question | Command | Limits |
|---|---|---|
| Does it parse and import? | `ruff check --no-cache --select E9 .`, then `python -c "import pkg"` from an environment built from the manifest | The second one needs a clean environment to mean anything |
| What do the tests really run? | `python -m pytest --collect-only -q`, `python -m pytest -ra` | See the testing reference for how suites pass while running nothing |
| What never executes? | `coverage run --branch -m pytest`, `coverage report --skip-covered --sort=cover` | Executed isn't checked, and code in subprocesses or `multiprocessing` workers looks unexecuted unless configured |
| Does it meet its own rules? | The project's linter and type checker, as configured | The configuration can hide problems, as below |
| What would a broad pass find? | `ruff check --no-cache --isolated --select F,B,S,C90,PLR09,DTZ,ASYNC,T20,ERA,UP,PGH,RUF100 --statistics .` | Shows the shape, not findings. `S101` in tests is expected, and `RUF100` here flags valid suppressions for rules outside this selection, so judge those under the project's own config |
| Do names and docstrings follow convention? | `ruff check --no-cache --isolated --select N,D,A --statistics .` | Conventions only, and the project's own come first |
| How big are the modules and functions? | `occam query size`, `occam query functions`, or `git ls-files -z '*.py' \| xargs -0 wc -l \| sort -n \| tail -20` | Size is a prompt to look. See the structure reference |
| Are there import cycles? | `occam query graph`, or `pylint --disable=all --enable=cyclic-import pkg` if available | Imports inside functions (Ruff `PLC0415`) often mark a cycle someone hid |
| Do declared and imported packages match? | `deptry .` if available | Plugin and runtime-only dependencies look unused |
| Any known vulnerabilities? | `pip-audit -r requirements.txt`, adding `--no-deps --disable-pip` if the file pins everything, or `pip-audit` inside the project's environment | Through `uvx` with no `-r`, it audits its own environment and reports nothing. It also can't say whether the code reaches the vulnerable path |
| What looks dead? | `vulture` if available | Dynamic use looks dead. Check before deleting |

Stating that a tool wasn't available is a fine result. Don't substitute a guess.

## Configuration that hides problems

Read this before trusting a clean run:

- `ignore_missing_imports = true` hides a package that doesn't exist from mypy.
- mypy skips the bodies of unannotated functions unless `check_untyped_defs` is on, so `def f(x): return 1 + "a"` reports success.
- A `# type: ignore` on a file's first line silences the whole file, even under `--strict`.
- Broad `per-file-ignores`, or an `exclude` covering real source.
- Coverage `omit`, and `addopts` that deselect tests.
- `filterwarnings = ignore`, and CI steps that continue on error.
- `try: import x / except ImportError:` with a fallback, which turns a missing dependency into quietly different behavior.

## Common in generated Python

Each of these has a direct way to confirm it:

| Sign | Confirm by |
|---|---|
| An import of a package no manifest declares, or that doesn't exist | Importing from a clean environment, and checking the registry entry is the package you think it is |
| An API that isn't on this version | The table in the APIs reference, and running with `-W error::DeprecationWarning` |
| `except Exception: pass`, or a broad `try` around a whole function | Injecting the failure and seeing whether anyone finds out |
| `pass`, `...` or `NotImplementedError` in a path reachable from an entry point | Calling it through that entry point |
| A check that returns `True` regardless of its arguments | A negative test |
| `foo.py` beside `foo_v2.py` or `foo_new.py` | Comparing callers. Often one is dead, and sometimes the two disagree |
| Near-identical functions across modules | Comparing edge cases before merging, since similar code can mean different things |
| An `ABC` or `Protocol` with one implementation, or a factory with one product | Searching for implementers, including dynamic registration |
| `async def` that never awaits, or a blocking call inside one | Reading the call chain, and Ruff `ASYNC` |
| `sys.path.insert`, hard-coded `/Users/...` paths | Running from another directory or a clean checkout |
| Sample or mock data outside tests | Tracing where the real source should come in |
| Tests that only assert on mocks, or print rather than assert | Breaking the code and watching whether they notice |

## Reading a large repository

Rank by risk, not by directory order. Files that are both complex and often changed tend to repay attention first, and `occam query history` gives the change counts, fix commits and owners, or `git log --format= --name-only | sort | uniq -c | sort -rn | head -30` without occam. Trace from entry points so findings connect to something a user reaches. The structure reference covers why a text search can't prove code unused.
