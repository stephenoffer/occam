# Python names, docstrings, comments and suppressions

Repository conventions win. PEP 8 and PEP 257 fill the gaps. This covers where generated code most often departs from them.

## Names

PEP 8 casing: `snake_case` for functions, variables and modules, `CapWords` for classes, `UPPER_CASE` for constants, a leading underscore for internals, and an `Error` suffix on exceptions that are errors.

- **Name the role, not the history.** `_v2`, `_new`, `_final`, `_fixed`, `enhanced_` and `improved_` record how the code got here. If your change leaves an old version dead, remove it, and mention any others you find.
- **Prefer the domain's word** to `Manager`, `Helper`, `Handler`, `Processor`, `data`, `info` and `result` when one exists. Check what the package already calls this.
- **Keep verbs consistent across a package.** If `get_` means a cheap lookup here, a network call shouldn't also be `get_`. Follow the existing convention for async pairs.
- **Put units in the name** when the type doesn't carry them: `timeout_seconds`, `size_bytes`. A `timedelta` removes the question.
- **Booleans read as predicates:** `is_active`, `has_access`. Make flag parameters keyword-only, so call sites say what they mean.
- **Avoid shadowing** builtins such as `id`, `type`, `list` and `input` in public signatures (Ruff `A`), and standard library modules in file names.
- **A public rename is an API change,** and that includes keyword argument names, since callers pass them by name. Keep an alias with a `DeprecationWarning`, and ask before removing the old name.
- **Tests name the behavior and condition:** `test_rejects_expired_token`, not `test_1` or `test_token_works`.

## Docstrings

- **Match the format already in use,** whether Google, NumPy or reST, and check how the docs are built. Sphinx and mkdocstrings render the wrong style badly.
- **Write what a caller can't guess:** behavior, errors raised, side effects, units, ownership, and whether it is safe across threads or tasks. Type hints already state the types, so don't repeat them.
- **Use PEP 257 form:** a one-line summary, a blank line, then detail. Public modules, classes and functions get one unless the name and types say everything. Private helpers get one when they are non-obvious.
- **Run the examples.** A `>>>` in a docstring is a claim, so check it with `python -m doctest` or `pytest --doctest-modules`. Build the docs with warnings as errors, for example `sphinx-build -W`, if the repository publishes them.
- **Keep docs true.** When behavior changes, update the docstring, README commands, changelog and deprecation notes in the same change.

Generated code tends to over-document the obvious ("Initializes the class") and under-document what matters (the invariant, the failure mode, the reason for the odd ordering).

## Comments

Comments carry what the code can't: why, not what. Good ones state an invariant, a unit, a workaround with its issue link, a measured tradeoff, an ordering that matters, or a security assumption.

Remove these from your own diff:

- Edit narration: `# Fixed the bug`, `# New helper`, `# Changed to use X`.
- Notes to the reader: `# Note that...`, `# You may want to...`.
- Comments restating the next line, and decorative banners. A file that needs banners may want splitting.
- Commented-out code. History keeps it.

A `TODO` names an owner or issue, and isn't a way to skip something the request asked for. Keep existing rationale that is still true, and leave existing comments you aren't changing the code for.

## Suppressions

`# noqa`, `# type: ignore`, `# pyright: ignore`, `# nosec`, `# pragma: no cover`, `pytest.mark.skip` and `filterwarnings("ignore")` all switch a check off.

- **Scope each one:** `# noqa: S603`, `# type: ignore[arg-type]`. The bare form also hides whatever goes wrong on that line later. Ruff's `PGH003` and `PGH004` find bare ones. `RUF100` and mypy's `warn_unused_ignores` find stale ones.
- **Say why on the same line.** The reason is what lets someone remove it later.
- **Don't use one to get green.** Fix the cause. If a suppression really is right, mention it in your report.
- **Configuration counts too:** `per-file-ignores`, `exclude`, coverage `omit`, a lower mypy strictness and `addopts` that deselect tests can all switch off more than an inline comment.
