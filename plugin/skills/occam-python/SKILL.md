---
name: occam-python
description: Python guidance on async and cancellation, shared mutable state, data-pipeline memory, time, money and text semantics, typing, packaging, modules, file size, large codebases, names, docstrings and comments, pytest and mocks, moved APIs, security sinks, notebooks. Use alongside occam to write, debug, audit or review Python where these matter.
disable-model-invocation: true
---

# Python

Tie choices to the project's supported versions and tools. Inspect `pyproject.toml`, lockfiles, packaging, interpreter versions, CI, and the established formatter, linter and type checker, then reuse the existing environment. Don't migrate tooling or raise the Python version to express a preference, or install a stack that isn't established.

## What goes wrong most

These failed in real runs, with or without it:

- **New module names.** `random.py`, `email.py` or `logging.py` beside a script shadows the standard library and breaks that script.
- **Partial splits.** Asked to break a module up, moving a third isn't done. Say what stayed and why.
- **Audits that trust tests.** A test asserting only on a mock can stay green when behavior breaks. Report it.
- **Notebooks.** Only a fresh kernel running top to bottom verifies one.

## Style and structure

Follow PEP 8, PEP 257 and the repository's public API conventions, sensibly. Avoid unnecessary metaclasses, decorators, dynamic attributes, import tricks, and classes wrapping stateless functions.

## Types

Type meaningful interfaces and data boundaries with the project's chosen checker. Avoid both untyped public contracts and ornate generics that add nothing. An annotation isn't input validation or a security check: data crossing a trust boundary still needs validating at runtime.

## Values and state

Watch for these common defects:

- Mutable default arguments and accidental aliasing. Know whether you need a shallow or a deep copy.
- Iterators and generators exhausted by a first pass, and lazy evaluation running later than you assume, for example closures capturing a loop variable.
- Mutable state shared across threads, tasks or requests.
- `assert` used for required validation, since `-O` removes it.
- `lru_cache` on a method, which keeps instances alive until evicted.

## Resources and errors

Use context managers for files, sockets, locks and sessions. Preserve causes with `raise ... from`. Distinguish expected domain errors from programmer errors, and don't catch `Exception` to make a failure disappear. `except BaseException` also intercepts cancellation and interpreter shutdown.

## Concurrency

Choose async, threads, processes or native and vectorized execution from the measured workload and actual runtime capabilities. Don't state universal GIL rules: they vary by interpreter build, and native extensions may release the GIL.

For asyncio:

- Anything blocking or CPU-heavy on the event loop stalls every other coroutine. Move it to a thread or process, and bound that too.
- `CancelledError` must propagate. Catching it to log is fine only if you re-raise, and cleanup in `finally` needs care not to swallow it.
- A semaphore bounds work in flight, but not tasks created. A task per item is itself the unbounded queue at large counts, so bound creation with a fixed worker pool or a bounded queue.
- Materializing an input with `list()` defeats a lazy source.
- Keep references to tasks you create, and don't leave any running when the caller is cancelled. Prefer structured concurrency, such as `TaskGroup`, where the supported versions allow it.
- Bound executor queues as well as workers.

## Data and memory

Inspect Python object overhead, dtypes, null semantics, copies, conversions, chunking and peak memory. A generator isn't sufficient if a later stage collects everything: `sorted`, `list`, string concatenation and many DataFrame operations all materialize. Check the whole pipeline, and measure peak RSS, not just elapsed time. `ru_maxrss` is bytes on macOS and kilobytes on Linux. Profile before optimizing, with `cProfile` or py-spy for time and `tracemalloc` or memray for allocations. Vectorize where the conversion cost doesn't dominate.

When replacing an in-memory stage with streaming, recheck what the old shape provided for free, such as ordering and what a failure leaves behind.

## Semantics worth deciding deliberately

Decide these on purpose where they affect correctness:

- **Time:** naive versus aware datetimes, timezone conversion, DST boundaries, and what "day" means.
- **Numbers:** `Decimal` for money, the rounding mode the domain requires, float comparison, NaN ordering.
- **Text:** bytes versus text, encodings, Unicode normalization, casefolding, locale-dependent sorting.
- **Order:** dict and set ordering assumptions, sort stability and ties.
- **Serialization:** `json` and `Decimal`, integer precision across languages, key order, `ensure_ascii`.

## Packaging

Test package imports and public exports. When packaging is affected, test the built artifact or a clean install, not only editable imports from the repository root, since those can hide missing modules and data files.

## Load only what applies

| When | Read |
|---|---|
| Modules, imports, packaging, environments, size, splitting, inheritance, large codebases | [structure](references/structure.md) |
| Names, docstrings, comments, `noqa` and `type: ignore` | [naming and docs](references/naming-and-docs.md) |
| Writing or judging tests | [testing](references/testing.md) |
| APIs from memory, untrusted input | [APIs and security](references/apis-and-security.md) |
| Async, threads, subprocess, values and time, memory, pandas, stubs | [runtime](references/runtime.md) |
| Auditing, alongside `occam-audit` if available | [auditing](references/auditing.md) |
| Notebooks and code cells | [notebooks](references/notebooks.md) |
