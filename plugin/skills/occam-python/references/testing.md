# Testing Python

Use the repository's framework. The core skill's verification reference covers which tests to write. This covers how Python suites come to pass while checking nothing.

## Tests that never run

Each of these leaves a green suite:

- **Two functions with the same name in one module:** the later one replaces the earlier, which never runs. Ruff `F811` finds them.
- **A `Test*` class with `__init__`:** pytest doesn't collect it, and only warns.
- **A name outside the collection patterns:** a `check_foo` function or a `foo_tests.py` file.
- **`async def` tests with no async plugin:** skipped with a warning before pytest 8.4, a failure from 8.4 on.
- **`-k` or `-m` matching nothing:** exit code 5, which `pytest ... | tail` hides unless the shell sets `pipefail`. Piping also hides real failures.
- **`python -m unittest` finding no tests:** prints `OK` and exits 0 through Python 3.11, exits 5 from 3.12.
- **A fully skipped run:** exits 0.

Check with `python -m pytest --collect-only -q` and compare the count to what you expect, and read `-ra` output for skips and xfails. `--strict-markers` catches mistyped marks, `--strict-config` catches mistyped settings, `xfail_strict = true` fails an xfail that starts passing, and `-W error` turns collection warnings into errors.

## Assertions that can't fail

- `assert (x == y, "message")` is a non-empty tuple, so it is always true. pytest only warns, and Ruff `F631` finds it.
- Lines after the raising call inside `with pytest.raises(...)` never run. Keep one statement in the block and assert after it.
- `pytest.raises(Exception)` also accepts the wrong error. Name the type and use `match=`.
- `assert result` and `is not None` pass for wrong values. Compare with the expected value.
- `Mock().anything()` returns a truthy `Mock`. `mock.called_once_with(...)`, without `assert_`, silently passes through Python 3.11 and raises from 3.12.
- A `try/except` in a test that doesn't re-raise turns failures into passes.
- `==` on floats fails or passes by accident, so use `pytest.approx`.

Show a test can fail by breaking the code in an isolated copy and watching it go red. Where a project has set up mutmut or cosmic-ray, use them on critical paths.

## Mocks

- **Patch where the name is looked up.** After `from os.path import exists` in `lib.py`, patching `os.path.exists` doesn't reach `lib`, so patch `lib.exists`.
- **Use `create_autospec` or `autospec=True`.** A plain `Mock` accepts any method and arguments, so a test keeps passing after the real API changes.
- **Mock at the outer boundary:** HTTP, time and files, with `tmp_path` and whatever the project already uses, such as `responses`, `respx`, `freezegun` or `time-machine`. Use `AsyncMock` for coroutines.
- **SQLite doesn't prove Postgres.** Types, `NULL` ordering, locking and JSON differ. Test important queries on the real engine when one is available, or say that you didn't.
- A test that only asserts on mock calls verifies wiring, not behavior.

## Fixtures and isolation

- Use `tmp_path`, `monkeypatch`, `capsys` and `caplog` rather than writing into the repository, changing directories or setting `os.environ` without restoring it.
- `session` and `module` fixtures share mutable state, and `autouse` fixtures act from a distance. Both create order dependence. Run a test alone, and in random order with `pytest-randomly` if the project has it.
- `set` order varies between processes because of string hash randomization, so a test can pass by luck.
- Freeze time, seed randomness, and poll with a deadline rather than `time.sleep`.
- `parametrize` with `ids=` reports each case separately, while a loop inside one test stops at the first failure.
- `python -m pytest` adds the current directory to `sys.path`, and plain `pytest` doesn't. That difference can hide a packaging bug.

## Async

Use the plugin the repository has, usually pytest-asyncio or anyio. Test cancellation directly: cancel the task and assert `CancelledError` propagates and no work continues. Put a timeout around anything that can hang, with `asyncio.timeout` or `pytest-timeout`, so that a deadlock fails rather than stalls CI. Plain `-W error` fails a test on "coroutine was never awaited". The narrower `-W error::RuntimeWarning` doesn't, under pytest.

## Beyond examples

Use Hypothesis's `@given` when a real property exists. `coverage run --branch -m pytest` shows what never ran, not that what ran was checked, so use it to find gaps rather than as a target.

## Replacing working code

The existing implementation is the best specification available, and a passing suite says nothing about what it doesn't cover. Before replacing code for speed or structure:

- Keep the old version callable, and compare old and new on generated and awkward inputs: signs and operator precedence, deep nesting, very long input, empty values and ties. Hypothesis makes this cheap. Compare failures as well as results.
- Get that comparison running early, and switch over only once it passes, so that being stopped partway leaves the old code working rather than half a rewrite.
- Watch for limits the new shape can hit. `compile`, `eval` and `ast.parse` raise `SyntaxError` past 200 nested parentheses. Recursion stops at 1000 frames by default, so a recursive walk fails on a long chain that a loop handled, and on some versions `ast.parse` itself raises `RecursionError` on one.

## Large suites

- Split unit and integration tests with registered markers, and find slow tests with `--durations=20`.
- `--import-mode=importlib` avoids `sys.path` collisions between same-named test files.
- `pytest-xdist` needs real isolation: each worker gets its own temp directory, database and ports.
- During work, run the affected tests with a path, `-k` or `--lf`. Run what CI runs before claiming the work is done.
- Rerunning until green isn't a fix. Quarantine a flaky test with an issue, and report it.
