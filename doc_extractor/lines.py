"""
Line-item extraction.

Two strategies, in order:

  1. the tables the source detected, when their heading row can be recognised;
  2. the text, when no usable table was found — rows are matched by shape
     (an index, a description, then trailing numbers).

Both run per page, so an invoice whose table continues onto a second page keeps
all of its rows. A row that cannot be understood is skipped rather than
half-filled, and the number of skipped rows is reported by the caller.
"""
from __future__ import annotations

import re

from . import patterns
from .model import LineItem
from .sources import Page
from .values import clean, parse_amount, parse_percentage

#: A text row that starts with a position number and ends with amounts.
_TEXT_ROW = re.compile(r"^\s*(\d{1,3})[.)]?\s+(.*?)\s+((?:-?[\d\s  .,]+|zw\.?|np\.?)(?:%)?(?:\s+\S+)*)$")


def extract_lines(pages: list[Page]) -> tuple[list[LineItem], int]:
    """Return the line items found across every page, and how many rows were skipped."""
    items: list[LineItem] = []
    skipped = 0

    for page in pages:
        from_tables, skipped_here = _from_tables(page)
        if from_tables:
            items.extend(from_tables)
            skipped += skipped_here
            continue
        from_text, skipped_here = _from_text(page)
        items.extend(from_text)
        skipped += skipped_here

    return items, skipped


# ------------------------------------------------------------------ table strategy


def _from_tables(page: Page) -> tuple[list[LineItem], int]:
    items: list[LineItem] = []
    skipped = 0

    for table in page.tables:
        if not table:
            continue
        mapping = _map_columns(table[0])
        # Without a description and an amount there is nothing worth reading;
        # this is most likely the totals box rather than the item table.
        if "description" not in mapping or "net_amount" not in mapping:
            continue

        for row in table[1:]:
            if _is_stop_row(row):
                break
            item = _row_to_item(row, mapping, page.number)
            if item is None:
                skipped += 1
            else:
                items.append(item)
    return items, skipped


def _map_columns(header: list[str]) -> dict[str, int]:
    """Map recognised column names to their index in the row."""
    mapping: dict[str, int] = {}
    for index, cell in enumerate(header):
        column = patterns.classify_heading(cell or "")
        if column and column not in mapping:
            mapping[column] = index
    return mapping


def _is_stop_row(row: list[str]) -> bool:
    joined = " ".join(clean(cell or "") for cell in row).lower()
    return any(joined.startswith(stop) for stop in patterns.TABLE_STOP)


def _row_to_item(row: list[str], mapping: dict[str, int], page: int) -> LineItem | None:
    def cell(name: str) -> str:
        index = mapping.get(name)
        if index is None or index >= len(row):
            return ""
        return clean(row[index] or "")

    description = cell("description")
    net_amount = parse_amount(cell("net_amount"))
    if not description and net_amount is None:
        return None

    return LineItem(
        description=description,
        quantity=parse_amount(cell("quantity")),
        unit_price=parse_amount(cell("unit_price")),
        net_amount=net_amount,
        vat_rate=parse_percentage(cell("vat_rate")),
        page=page,
        raw=[clean(c or "") for c in row],
    )


# ------------------------------------------------------------------- text strategy


def _from_text(page: Page) -> tuple[list[LineItem], int]:
    items: list[LineItem] = []
    skipped = 0
    started = False

    for line in page.lines():
        stripped = clean(line)
        if not stripped:
            continue
        lowered = stripped.lower()

        if any(lowered.startswith(stop) for stop in patterns.TABLE_STOP):
            if started:
                break
            continue

        # The heading row tells us the table has begun.
        if not started and patterns.classify_heading(stripped.split(" ")[0]) == "index":
            started = True
            continue

        match = _TEXT_ROW.match(stripped)
        if not match:
            continue

        item = _text_row_to_item(match, page.number, stripped)
        if item is None:
            skipped += 1
        else:
            items.append(item)
            started = True

    return items, skipped


def _text_row_to_item(match: re.Match, page: int, raw: str) -> LineItem | None:
    """Turn a matched text row into an item.

    The tail of the row holds, in order, quantity, unit price, VAT rate and net
    amount. They are read from the right, because the description on the left can
    itself contain numbers ("Hosting aplikacji (12 miesięcy)") while the trailing
    columns are always in the same order.
    """
    description_and_tail = f"{match.group(2)} {match.group(3)}".strip()
    tokens = description_and_tail.split(" ")

    numbers: list[str] = []
    index = len(tokens)
    # Walk backwards collecting numeric-looking tokens, joining the pieces of a
    # space-separated thousands group such as "4 500,00".
    while index > 0 and len(numbers) < 8:
        token = tokens[index - 1]
        if _numeric(token):
            numbers.insert(0, token)
            index -= 1
        else:
            break

    merged = _merge_thousands(numbers)
    if len(merged) < 2:
        return None

    description = " ".join(tokens[:index]).strip()
    vat_rate = None
    amounts = merged
    for position, token in enumerate(merged):
        if "%" in token or token.lower().strip(".") in ("zw", "np"):
            vat_rate = parse_percentage(token)
            amounts = merged[:position] + merged[position + 1:]
            break

    net_amount = parse_amount(amounts[-1]) if amounts else None
    unit_price = parse_amount(amounts[-2]) if len(amounts) >= 2 else None
    quantity = parse_amount(amounts[-3]) if len(amounts) >= 3 else None

    if net_amount is None or not description:
        return None

    return LineItem(
        description=description, quantity=quantity, unit_price=unit_price,
        net_amount=net_amount, vat_rate=vat_rate, page=page, raw=[raw],
    )


def _numeric(token: str) -> bool:
    stripped = token.strip("()%")
    if stripped.lower().strip(".") in ("zw", "np"):
        return True
    return bool(re.fullmatch(r"-?[\d.,]+%?", stripped)) and any(c.isdigit() for c in stripped)


def _merge_thousands(tokens: list[str]) -> list[str]:
    """Join "4" and "500,00" back into "4 500,00".

    A group of exactly three digits following another number is a thousands
    group, never a separate column.
    """
    merged: list[str] = []
    for token in tokens:
        if (
            merged
            and re.fullmatch(r"\d{3}([.,]\d+)?", token)
            and re.fullmatch(r"-?\d{1,3}", merged[-1])
        ):
            merged[-1] = f"{merged[-1]} {token}"
        else:
            merged.append(token)
    return merged
