"""A set of named cells, each holding a number or a formula."""

from pricemodel.formula import evaluate, parse


class CircularReference(Exception):
    """A cell's formula depends on the cell itself."""


class Workbook:
    def __init__(self):
        self._cells = {}

    def set(self, name, value):
        """Store a number, or a formula if value is a string starting with '='."""
        if isinstance(value, str) and value.startswith("="):
            self._cells[name] = parse(value[1:])
        else:
            self._cells[name] = float(value)

    def get(self, name):
        """Return the cell's current value. A cell that has never been set reads as 0."""
        return self._read(name, set())

    def names(self):
        return sorted(self._cells)

    def _read(self, name, reading):
        cell = self._cells.get(name, 0.0)
        if isinstance(cell, float):
            return cell
        if name in reading:
            raise CircularReference(f"circular reference involving {name}")
        reading.add(name)
        try:
            return evaluate(cell, lambda ref: self._read(ref, reading))
        finally:
            reading.discard(name)
