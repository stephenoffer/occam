# Notebooks and code cells

A fix in one cell is a small change. Don't move a notebook's logic into modules or reorganize its cells unless the request calls for that.

## What makes a notebook wrong while it looks right

- **Hidden state.** The kernel remembers names from cells since edited or deleted, and a cell can use a name that only a later cell defines. Saved outputs show what happened once, not what the code does now.
- **Execution order.** `execution_count` values that don't rise from top to bottom show the cells ran out of order, so the saved results may not be reproducible.
- **Unpinned installs.** `!pip install pandas` picks whatever is current, and can install into a different environment than the kernel uses. `%pip install pandas==2.2.3` targets the kernel. A declared environment is better still.
- **Machine-specific paths and unseeded randomness.** `/Users/...` and `/content/drive/...` fail elsewhere, and results change between runs.
- **Secrets and personal data in outputs.** Saved outputs are committed along with the code, and printed tokens, error messages and data previews all end up there.

## The check that counts

A notebook is verified when a fresh kernel runs it top to bottom. Save the result elsewhere rather than overwriting the source:

```bash
jupyter nbconvert --to notebook --execute --output-dir "$(mktemp -d)" analysis.ipynb
```

`papermill` does the same with parameters. Running one cell in a live kernel only shows that cell works with whatever state the kernel holds, so report it that way. If the data or hardware isn't available, say so, and run what you can on a sample. If no kernel can run here, say so. Stale outputs mislead, so either execute the code cells in order in a new process and save what they print, saying it wasn't Jupyter, or clear them and say a rerun will fill them.

`nbqa ruff` and `nbqa mypy` run the usual checkers over cells, if available. Top-level `await` and `%` magics are notebook syntax, so they won't work if the code moves to a module.

## Editing

- Notebooks are JSON. Use a notebook-aware editing tool when there is one, and keep the file valid JSON otherwise. Text edits that break `source` lists or metadata are easy to miss.
- Clear outputs before committing unless the repository keeps them on purpose. `nbstripout` or a pre-commit hook does this if the project uses one.
- Prefer one idea per cell. A cell long enough to need scrolling usually contains a function waiting to be named.

## When code outgrows the notebook

Reused or production logic is easier to test in a module that the notebook imports, with `%autoreload` during development. Propose the move when the same code appears in several notebooks or cells, or when something depends on the results, and do it when asked. Large data work follows the same rules as anywhere else in Python: check dtypes, copies and peak memory.
