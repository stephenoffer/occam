"""Plain text tables."""

from collections.abc import Sequence


def render_rows(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [max([len(header), *(len(row[index]) for row in rows)]) for index, header in enumerate(headers)]
    def line(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * width for width in widths]), *(line(row) for row in rows)])
