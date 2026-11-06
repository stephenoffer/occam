# Python runtime traps

Each of these passes a quick read and then fails quietly.

## Concurrency

- **`asyncio.TaskGroup` raises an `ExceptionGroup`,** so `except ValueError` around it doesn't catch a task's `ValueError`. Use `except*` from 3.11, or handle the error inside the task.
- **Cancelling `asyncio.to_thread` cancels the wait, not the thread.** The thread runs to completion, so blocking work needs its own timeout or stop signal.
- **`executor.submit` keeps an exception in the future.** Nothing surfaces until something calls `.result()` or `.exception()`, so a fire-and-forget submit loses errors.

## Subprocess

`subprocess.run` doesn't raise on a non-zero exit without `check=True`, so a failed command looks like success. It has no default timeout either.

## pandas

- **Chained assignment** such as `df[mask]["b"] = 5` changes nothing under Copy-on-Write, the default in current pandas. Use `df.loc[mask, "b"] = 5`.
- **`merge` on duplicate keys multiplies rows** without complaint. `validate="one_to_one"` or `"many_to_one"` states the grain you expect, and raises otherwise.
- **`groupby` drops NaN keys by default,** which silently loses rows from totals. `dropna=False` keeps them.

## Text

`str.splitlines()` splits on more than newlines, such as U+2028, so it can break line-delimited formats containing those characters.

## Stubs and extensions

- A `.pyi` stub is a claim about the runtime that nothing enforces by default. `python -m mypy.stubtest pkg` compares the two.
- A `.pyx` or `.pxd` file only takes effect once built, so tests can pass against a stale build. Rebuild first, and check that any `nogil` section touches no Python objects.
