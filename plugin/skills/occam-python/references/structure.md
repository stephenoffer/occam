# Python structure, size and large codebases

The repository's layout and configured limits come first. This covers what commonly goes wrong in Python. General design judgment is in the core skill's design reference.

## Layout

- **New packages:** a `src/` layout makes tests import the installed package, so a missing module or data file fails in testing rather than for users. Don't move an existing project to it as a side effect.
- **Entry points:** keep logic importable. `[project.scripts]` or `__main__.py` calls a `main()`, and `if __name__ == "__main__":` does nothing else. Parse arguments with `argparse` or the CLI library the project already has. Demo code at the bottom of a library module is dead weight.
- **`__init__.py`:** public re-exports and `__all__` at most. No I/O, heavy imports, or logic that works in only one import order.
- **Module names:** `random.py`, `email.py`, `logging.py` or `types.py` next to a script shadow the standard library, and the failure shows up somewhere else entirely. A module named for what it serves doesn't become a dumping ground the way `utils.py`, `helpers.py` and `common.py` do.
- **Import paths:** fix packaging rather than editing `sys.path`. An edit that works from one directory breaks from another.
- **Dependencies:** a library declares ranges, and an application pins with a lockfile. A single-file script can declare its own with PEP 723 inline metadata. A typed library ships `py.typed`. Test, lint and documentation tools go in a dev group or extra, not runtime dependencies. A package from an optional extra is imported inside the function that needs it, with an error naming the extra to install.

## Environment and packaging

- **Use the project's interpreter.** Run Python, tests and tools through its environment, such as `uv run`, `poetry run` or the virtualenv's `python`, and check `sys.executable` when a result surprises you.
- **Install only into that environment, with its manager.** No global `pip install`, `sudo pip` or `--break-system-packages`. In a uv or Poetry project, `pip install` bypasses the lockfile, so use `uv add` or `poetry add` and commit the updated lockfile.
- **Inspecting a package can run it.** `pip install`, `pip download` of an sdist and `setup.py` all execute the package's build code. Read its metadata or wheel instead, or build it in a sandbox.
- **Supported versions.** Syntax and standard-library APIs newer than `requires-python` break users on the floor, so CI tests the floor. Check that every native dependency publishes wheels for the platforms and Python versions you support, or installs need a compiler.
- **Type safety is claimed for what the checker covered.** Run it as CI runs it, over the package, not on one file. Prefer a dependency's own types to separate `types-*` stubs where it ships them.
- **Configuration and logging:** read the environment once, at the edge, and pass values down. Applications configure logging at startup. Libraries only call `logging.getLogger(__name__)`, and leave handlers, `basicConfig` and `print` alone.

## Imports and dependency direction

- Lower layers don't import higher ones: domain code doesn't import the web framework, the CLI or session setup. If the repository uses import-linter or Tach, add a contract rather than a comment.
- A circular import is a design finding, so move the shared piece down. Importing inside a function hides a runtime cycle without removing it. It is fine for deferring a heavy module. `if TYPE_CHECKING:` is fine for names only a static checker reads, but Pydantic and `typing.get_type_hints` evaluate annotations at runtime, and then fail.
- Import-time code runs for every importer, every test and every `--help`. Keep network, files, databases, threads and order-dependent registries out of it. `python -X importtime -c "import pkg"` shows what startup costs.
- Star imports hide where names come from, outside a deliberate re-export. A leading underscore marks internals, and `__all__` states the public surface.

## Classes, functions and base classes

Module-level functions by default. A class earns its place by protecting an invariant over state, or because callers substitute implementations.

- Use `dataclass` for plain records, with `frozen=True` if nothing should mutate them. A class with only `__init__` and one method is a function. A class with only static methods is a module.
- Use `Protocol` when the contract is the commonality and implementers are unrelated, and `ABC` for a real family with a shared lifecycle. Neither suits a single implementation with no boundary behind it.
- Extend an existing base class when its contract fits, and call `super().__init__()`. Reimplementing what the base provides leaves two versions to drift. A subclass that raises `NotImplementedError` for an inherited method isn't substitutable.
- `**kwargs` forwarding, `__getattr__`, metaclasses and signature-changing decorators hide contracts from readers, search and type checkers. Each needs a reason.

## Size limits

Use what the repository configures. With nothing configured, treat these as prompts to look, not as errors. They are the defaults of the common linters rather than research findings, and occam-audit's scanner deliberately flags only larger outliers for functions, so a clean scan doesn't mean code is within them.

| Measure | Look past | Source |
|---|---:|---|
| Lines in a module | 1000 | pylint `max-module-lines` |
| Cyclomatic complexity | 10 | Ruff `C901` |
| Branches in a function | 12 | Ruff `PLR0912` |
| Statements in a function | 50 | Ruff `PLR0915` |
| Return statements | 6 | Ruff `PLR0911` |
| Arguments | 5 | Ruff `PLR0913` |
| Nested blocks | 5 | Ruff `PLR1702` (preview) |
| Public methods in a class | 20 | Ruff `PLR0904` (preview) |
| Line length | 88 | Black and Ruff. PEP 8 says 79 and pylint 100 |

When you reach one:

- **Adding to an oversized file:** code with its own responsibility goes in a new module, named for that responsibility. A small fix stays where it is, and one more of a kind the file already holds can follow its siblings, which is worth mentioning.
- **Splitting what is already there:** a separate change. Mention it, and do it only if the request asks, as with any unrelated cleanup.
- **Cut at a seam, not a number:** split where calls across the boundary are few and each side has a name. Moving lines until a file is under a limit leaves the same coupling in more files. A flat dispatch table, a long parametrized test table or a generated file can be right as it is.

## Splitting a module safely

1. Lock behavior first. Run the tests, and add characterization tests for the public surface if they don't reach it.
2. Move code in a change that does nothing else. Renames and fixes go in the next one, so the diff stays reviewable.
3. Keep the old import path working if anything outside the package could use it: a re-export, or a module `__getattr__` that emits `DeprecationWarning`.
4. Search for strings as well as imports, because these break at runtime rather than at import: `mock.patch("pkg.mod.name")` targets, `importlib` calls, entry points in `pyproject.toml`, Celery or RQ task names, logging configuration, Django settings and migrations, Sphinx directives, and anything pickled, since pickle stores the module path.
5. Import each new module alone in a fresh process, as in `python -c "import pkg.part"`. A cycle can stay hidden while one import order happens to work.
6. Run the tests, the type checker and, if packaging is affected, an import from the built artifact.

## Large codebases

- **Find your way without reading everything.** Start at entry points, follow imports and search for symbols. `occam query` does this: `entry`, `outline`, `find` and `graph`. occam-audit, if available, covers mapping an unfamiliar codebase. A text search misses `getattr`, registries, plugin entry points, dependency injection and framework autodiscovery, so "nothing uses this" needs runtime or coverage evidence, and coverage shows code run in subprocesses or `multiprocessing` workers as unexecuted unless configured for them.
- **Boundaries.** A package exposes a small surface through `__init__.py` and `__all__`, and keeps the rest in `_private` modules. Shared code is a package with an owner, not a folder everyone adds to.
- **Types as contracts.** Raise strictness per module, with mypy's `[[tool.mypy.overrides]]` or pyright's `strict` list, so typing improves without a flag day. `Any` at a boundary spreads to everything downstream. Lowering a global setting to land one change costs everyone.
- **Migrations.** Use a codemod such as LibCST or an autofix rule rather than regular expressions, and keep a recorded baseline that can only shrink. Deprecate with `warnings.warn(..., DeprecationWarning, stacklevel=2)`, and run tests with those warnings as errors so that callers get found.
- **Process model.** Module-level state exists once per process, so a cache or counter is per worker under Gunicorn, Celery or `multiprocessing`. Create connections after forking. The default start method is `spawn` on macOS and Windows. On Linux it is `fork` before 3.14 and `forkserver` from 3.14, so arguments need to be picklable, and code can pass on one platform and fail on another.
- **Monorepos.** Use one workspace tool, such as uv workspaces, Pants or Bazel, with dependencies declared per package. A shared `sys.path` lets code import what it never declared.
- **Large test suites.** The testing reference covers selection and speed.
