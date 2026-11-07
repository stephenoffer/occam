"""Rendering the customer receipt (40 columns, the width of the receipt printers)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from string import Template

from till.basket import Basket
from till.money import fmt
from till.tender import Tender

WIDTH = 40
TEMPLATE = Template((Path(__file__).parent / "templates" / "receipt.txt").read_text(encoding="utf-8"))


def two_columns(left: str, right: str, width: int = WIDTH) -> str:
    space = max(1, width - len(left) - len(right))
    return f"{left}{' ' * space}{right}"


def line_rows(basket: Basket) -> list[str]:
    rows = []
    for line in basket.lines:
        rows.append(two_columns(line.description[: WIDTH - 10], fmt(line.total_pence)))
        if line.qty > 1:
            rows.append(f"  {line.qty} @ {fmt(line.unit_pence)}")
    return rows


def render_receipt(*, store_name: str, till: int, sale: str, at: datetime, basket: Basket,
                   tenders: list[Tender], change_pence: int) -> str:
    return TEMPLATE.substitute(
        store_name=store_name,
        till=till,
        sale=sale,
        when=at.strftime("%d/%m/%Y %H:%M"),
        lines="\n".join(line_rows(basket)),
        total_line=two_columns("TOTAL", fmt(basket.total_pence)),
        tender_lines="\n".join(two_columns(t.type.upper(), fmt(t.pence)) for t in tenders),
        change_line=two_columns("CHANGE", fmt(change_pence)),
        items=basket.item_count,
    ).rstrip("\n") + "\n"
