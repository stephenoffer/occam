# pricemodel

A small calculation engine for pricing models. A model is a set of named cells, each
holding a number or a formula.

    python -m pricemodel models/sample.json                 # print every cell
    python -m pricemodel models/sample.json --cell margin   # print selected cells

Output is one `name = value` line per cell, sorted by name when printing every cell.
A circular reference prints an error to stderr and exits with status 2.

## Library

    from pricemodel import Workbook, CircularReference

    wb = Workbook()
    wb.set("price", 120)
    wb.set("cost", "=price * 0.6")
    wb.get("cost")     # 72.0
    wb.names()         # ["cost", "price"]

## Formulas

A formula is a string starting with `=`. It can use numbers, cell names, `+ - * /`,
comparisons (`= <> < <= > >=`, which give 1 or 0), parentheses, and the functions
`SUM`, `MIN`, `MAX`, `ABS`, `ROUND(x, digits)` and `IF(test, then, else)`.

Cell names may contain letters, digits, `_` and `.`, and must not start with a digit.

- A cell that has never been set reads as 0, so formulas can refer to cells that are
  set later.
- `IF` only evaluates the branch it takes, so `=IF(units = 0, 0, unit_cost)` is safe
  even when reading `unit_cost` would raise.
- Arithmetic errors such as division by zero raise from `get`, for the cell and
  anything that reads it, until an edit fixes the cause.
- A syntax error raises `FormulaError` from `set`.

Run the tests with `pytest`.
