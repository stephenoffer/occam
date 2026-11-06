"""A set of named cells, each holding a number or a formula."""

from pricemodel.formula import evaluate, parse, references


class CircularReference(Exception):
    """A cell's formula depends on the cell itself."""


class Workbook:
    def __init__(self):
        self._cells = {}
        self._references = {}
        self._readers = {}
        self._values = {}

    def set(self, name, value):
        """Store a number, or a formula if value is a string starting with '='."""
        is_formula = isinstance(value, str) and value.startswith("=")
        content = parse(value[1:]) if is_formula else float(value)
        for ref in self._references.pop(name, ()):
            self._readers[ref].discard(name)
        if is_formula:
            refs = references(content)
            self._references[name] = refs
            for ref in refs:
                self._readers.setdefault(ref, set()).add(name)
        self._cells[name] = content
        self._recalculate(name)

    def get(self, name):
        """Return the cell's current value. A cell that has never been set reads as 0."""
        value = self._values.get(name, 0.0)
        if isinstance(value, Exception):
            raise value
        return value

    def names(self):
        return sorted(self._cells)

    def _recalculate(self, name):
        cell = self._cells[name]
        if isinstance(cell, float):
            self._values[name] = cell
        else:
            try:
                self._values[name] = evaluate(cell, self.get)
            except ArithmeticError as exc:
                self._values[name] = exc
        for reader in self._readers.get(name, ()):
            self._recalculate(reader)
