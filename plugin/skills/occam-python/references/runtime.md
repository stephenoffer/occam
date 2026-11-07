# Python runtime traps

Each of these passes a quick read and then fails quietly.

## Concurrency

- **`asyncio.TaskGroup` raises an `ExceptionGroup`,** so `except ValueError` around it doesn't catch a task's `ValueError`. Use `except*` from 3.11, or handle the error inside the task.
- **Cancelling `asyncio.to_thread` cancels the wait, not the thread.** The thread runs to completion, so blocking work needs its own timeout or stop signal.
- **`executor.submit` keeps an exception in the future.** Nothing surfaces until something calls `.result()` or `.exception()`, so a fire-and-forget submit loses errors.
- **Don't await while holding a threading lock.** Another coroutine that wants it blocks the loop's only thread. Use `asyncio.Lock` with `async with`, and keep network calls out of any lock.
- **Compound updates race with or without the GIL.** `x += 1`, check-then-set and read-modify-write on a shared object take several steps, so another thread can run between them. Use a lock.
- **Check a client's thread-safety before sharing it.** A SQLAlchemy `Session` and a `sqlite3` connection belong to one thread, and many SDK clients don't promise more. Make one per thread or task, or use a pool.
- **`loop.run_in_executor` and `executor.submit` don't carry `contextvars`,** so request ids and tenant context are missing in the worker. `asyncio.to_thread` copies them, and `contextvars.copy_context().run` does it by hand.
- **Shutdown can drop work.** `shutdown(wait=False)` returns at once and `cancel_futures=True` discards queued tasks. Decide which results may be lost.
- **A pool waiting on itself deadlocks.** A task that submits to its own bounded pool and waits for the result stalls once every worker is waiting.
- **Process pools pickle what they run,** so a lambda or nested function fails, and each worker holds its own copy of what it is given. Pass large read-only data by path or shared memory. Under spawn or forkserver, the defaults everywhere but Linux before 3.14, each worker imports the main module again, so create pools under `if __name__ == "__main__":`.
- **`asyncio.run` inside a running loop raises.** A library offers the coroutine and leaves running the loop to the application.
- **`os.cpu_count()` counts the host,** not a container's CPU quota or the process's affinity. `os.process_cpu_count()` (3.13) respects affinity. Read the quota where it matters.

## Values and state

- **A list or dict in a class body is shared by every instance.** Create it in `__init__`, or use a dataclass `default_factory`.
- **Returning internal state lets callers change it.** Return a copy, a tuple or a read-only view when they shouldn't.
- **Directory listings, globs, `as_completed` and SQL without `ORDER BY` have no defined order.** Sort before the order reaches output or a comparison.
- **`is` compares identity.** Use it for `None` and other singletons only. `x is 1` and `s is "a"` depend on interning.
- **A dict key or set member must not change while stored.** Hash on fields that don't change.
- **Removing from a collection while looping over it** skips list items, and raises for dicts and sets. Loop over a copy or build a new one.
- **`bool` is an `int`,** so `isinstance(x, int)` and JSON `true` pass an integer check. Exclude it where it isn't valid.
- **`if not x` and `x or default` treat 0, `""` and `[]` like `None`.** Test for `None` itself where 0 or an empty value means something, and keep missing, null, empty and zero apart.
- **Cleanup in `__del__` runs when the collector decides,** and maybe never. Release resources with a context manager.
- **A decorator without `functools.wraps`** hides the wrapped function's name, docstring and signature.
- **Callbacks, closures over `self`, stored exceptions with tracebacks, and caches keep objects alive.** Drop them when the work ends.
- **`hash()` of `str` and `bytes` changes per process.** Use `zlib.crc32` or `hashlib` for anything shared or stored.
- **Code that samples or shuffles takes a `random.Random` or a seed,** so a failure can be replayed. Secrets come from `secrets`.

## Numbers

- **NaN equals nothing, itself included,** so `== nan` is always false and sorting with NaN is unreliable. Infinity and `-0.0` pass through arithmetic silently. Use `math.isnan` and decide which values are allowed.
- **NumPy and pandas integers are fixed width** and wrap on overflow without an error, unlike Python's `int`.
- **`/` between ints returns a float,** and `//` and `%` floor toward negative infinity: `-7 // 2` is `-4`.

## Time

Measure elapsed time and deadlines with `time.monotonic()` or `time.perf_counter()`. `time.time()` jumps when the clock is set or synced.

## Subprocess

`subprocess.run` doesn't raise on a non-zero exit without `check=True`, so a failed command looks like success. It has no default timeout either. `text=True` decodes with the locale's encoding, which differs between machines, so pass `encoding=` and `errors=`.

## pandas

- **Chained assignment** such as `df[mask]["b"] = 5` changes nothing under Copy-on-Write, the default in current pandas. Use `df.loc[mask, "b"] = 5`.
- **`merge` on duplicate keys multiplies rows** without complaint. `validate="one_to_one"` or `"many_to_one"` states the grain you expect, and raises otherwise.
- **`groupby` drops NaN keys by default,** which silently loses rows from totals. `dropna=False` keeps them.

## Text

`str.splitlines()` splits on more than newlines, such as U+2028, so it can break line-delimited formats containing those characters.

`len(s)` counts code points. A byte limit needs `len(s.encode())`, and what a user sees as one character can be several code points. Normalizing an identifier with NFKC, `casefold` or `strip` can merge two different users, so decide which form is the key and check for collisions.

## Data and memory

- **Size batches by bytes,** not rows, since a few wide records can exceed the budget.
- **A NumPy slice or `memoryview` keeps its whole parent buffer alive.** Copy a small slice you keep for long.
- **Whether a conversion copies** depends on dtype, layout and library version. `np.shares_memory` tells you.
- **Dense numbers belong in arrays or columnar frames,** not lists of objects, which cost dozens of bytes each.
- **A join or `groupby` holds a hash table of its keys.** Estimate the distinct keys before running it on everything.
- **Device memory is fixed,** and frameworks cache allocations. Size batches against the device, and read the framework's peak, such as `torch.cuda.max_memory_allocated()`.
- **`zip()` stops at the shortest input.** Pass `strict=True` (3.10) where lengths must match.

## Stubs and extensions

- A `.pyi` stub is a claim about the runtime that nothing enforces by default. `python -m mypy.stubtest pkg` compares the two.
- A `.pyx` or `.pxd` file only takes effect once built, so tests can pass against a stale build. Rebuild first, and check that any `nogil` section touches no Python objects.
