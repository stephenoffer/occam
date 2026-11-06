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
        self._forget(name)

    def get(self, name):
        """Return the cell's current value. A cell that has never been set reads as 0."""
        return self._read(name, set())

    def names(self):
        return sorted(self._cells)

    def _forget(self, name):
        self._values.pop(name, None)
        for reader in self._readers.get(name, ()):
            if reader in self._values:
                self._forget(reader)

    def _read(self, name, reading):
        if name in self._values:
            return self._values[name]
        cell = self._cells.get(name, 0.0)
        if isinstance(cell, float):
            return cell
        if name in reading:
            raise CircularReference(f"circular reference involving {name}")
        reading.add(name)
        try:
            value = evaluate(cell, lambda ref: self._read(ref, reading))
        finally:
            reading.discard(name)
        self._values[name] = value
        return value
