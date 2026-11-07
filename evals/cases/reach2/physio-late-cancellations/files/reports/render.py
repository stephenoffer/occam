"""Plain-text rendering of the monthly figures, for the email to the clinical leads."""

from __future__ import annotations

from reports.monthly import MonthlyFigures

HEADINGS = ("Clinician", "Booked", "Attended", "Cancelled", "DNA", "DNA rate", "Hours")


def _rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _row(name: str, figures: dict) -> tuple[str, ...]:
    return (name, str(figures["booked"]), str(figures["attended"]), str(figures["cancellations"]),
            str(figures["dna"]), _rate(figures["dna_rate"]), f"{figures['treatment_minutes'] / 60:.1f}")


def render(figures: MonthlyFigures) -> str:
    rows = [HEADINGS]
    rows += [_row(entry["clinician"], entry) for entry in figures.clinicians]
    rows.append(_row("All clinicians", figures.totals))
    widths = [max(len(row[i]) for row in rows) for i in range(len(HEADINGS))]
    lines = [f"Kestrel Physio, {figures.month}", ""]
    for index, row in enumerate(rows):
        cells = [row[0].ljust(widths[0])] + [cell.rjust(width) for cell, width in zip(row[1:], widths[1:])]
        lines.append("  ".join(cells))
        if index == 0 or index == len(rows) - 2:
            lines.append("  ".join("-" * width for width in widths))
    lines += ["", f"New patients: {figures.new_patients}"]
    return "\n".join(lines)
