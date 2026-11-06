# Contributing

CI runs three checks on every pull request:

- `pytest`
- `lint-imports`, which enforces the contracts in `.importlinter`
- `mypy tidewater`, with per-module strictness in `mypy.ini`

`lint-imports` and `mypy` come from the `ci` extra and aren't installed on most machines, so CI is usually the first place they run. Contract and strictness settings are owned by the architecture group. A change that needs an exception goes to them first, it doesn't get added in the same pull request.

Import-linter looks at every import statement, including ones inside functions and under `TYPE_CHECKING`.
