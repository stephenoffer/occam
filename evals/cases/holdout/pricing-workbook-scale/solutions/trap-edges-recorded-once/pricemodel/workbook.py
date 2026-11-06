"""A set of named cells, each holding a number or a formula."""

from pricemodel.formula import evaluate, parse, references


class CircularReference(Exception):
    """A cell's formula depends on the cell itself."""


class _Failure:
    __slots__ = ("error",)

    def __init__(self, error):
        self.error = error


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

        if is_formula and name not in self._references:
            refs = references(content)
            self._references[name] = refs
            for ref in refs:
                self._readers.setdefault(ref, set()).add(name)
        self._cells[name] = content
        self._forget(name)

    def get(self, name):
        """Return the cell's current value. A cell that has never been set reads as 0."""
        if name not in self._values:
            self._compute(name)
        value = self._values[name]
        if type(value) is _Failure:
            raise value.error
        return value

    def names(self):
        return sorted(self._cells)

    def _forget(self, name):
        values, readers = self._values, self._readers
        values.pop(name, None)
        stack = list(readers.get(name, ()))
        while stack:
            cell = stack.pop()
            if cell in values:
                del values[cell]
                stack.extend(readers.get(cell, ()))

    def _compute(self, root):
        values, references_of = self._values, self._references
        visiting = set()
        stack = [root]
        while stack:
            cell = stack[-1]
            if cell in values:
                stack.pop()
                continue
            if cell not in visiting:
                visiting.add(cell)
                pending = [ref for ref in references_of.get(cell, ())
                           if ref not in values and ref not in visiting]
                if pending:
                    stack.extend(pending)
                    continue
            stack.pop()
            visiting.discard(cell)
            values[cell] = self._evaluate(cell)

    def _evaluate(self, name):
        content = self._cells.get(name, 0.0)
        if isinstance(content, float):
            return content
        try:
            return evaluate(content, self._read_stored)
        except Exception as exc:
            return _Failure(exc)

    def _read_stored(self, name):
        if name not in self._values:
            raise CircularReference(f"circular reference involving {name}")
        value = self._values[name]
        if type(value) is _Failure:
            raise value.error
        return value
