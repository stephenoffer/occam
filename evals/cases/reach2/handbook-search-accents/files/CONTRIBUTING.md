# Contributing to findoc

findoc is maintained by the internal tools team, but anyone can send a change. The handbook
pages themselves have their own owners; this file is about the tool.

## Setting up

Python 3.10 or later, nothing else. From the repository root:

```
python -m pytest -q
python -m findoc search handbook laptop
```

## Making a change

- Keep changes small and say in the pull request what a user will notice.
- Add or update tests next to the behaviour you changed. `tests/conftest.py` has a `make_tree`
  fixture for building a small handbook in a temporary directory.
- Put the user-visible part in the `Unreleased` section of CHANGELOG.md.
- Significant design decisions get a short ADR in `docs/adr/`, numbered in order.

## Style

- Standard library only. findoc runs on every laptop and in the chat bot's container, and we
  don't want to manage dependencies for either.
- Type hints on public functions. Docstrings say what a function is for, not how.
- No printing from library code; only `findoc/cli.py` and `findoc/output.py` print.

## Releasing

Bump `__version__` in `findoc/__init__.py` and `version` in `pyproject.toml`, move the
Unreleased notes under the new version, and tag the merge commit. The chat bot picks up new
tags within the hour.
