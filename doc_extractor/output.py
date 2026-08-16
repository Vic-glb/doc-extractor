"""
JSON and CSV output.

Both formats keep the confidence next to every value. A consumer that only wants
the numbers can ignore those columns, but it can never be misled into treating a
guess as a certainty, because there are no guesses to begin with — an unknown
field is empty and marked `missing`.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .model import Invoice

#: Header of the fields CSV.
FIELD_COLUMNS = ("field", "value", "confidence", "note", "page", "evidence")
#: Header of the line-items CSV.
LINE_COLUMNS = ("invoice_number", "line_no", "description", "quantity",
                "unit_price", "vat_rate", "net_amount", "page")


def write_json(invoices: list[Invoice], path: Path) -> None:
    """Write every extracted invoice as one JSON document."""
    payload = {
        "invoices": [invoice.as_json() for invoice in invoices],
        "summary": {
            "documents": len(invoices),
            "with_errors": sum(1 for i in invoices if i.has_errors()),
            "fields_needing_review": sum(len(i.fields_needing_review()) for i in invoices),
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_fields_csv(invoices: list[Invoice], path: Path, delimiter: str = ";") -> None:
    """One row per extracted field, across all documents."""
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(("source",) + FIELD_COLUMNS)
        for invoice in invoices:
            for name, field in invoice.all_fields().items():
                writer.writerow([
                    invoice.source,
                    name,
                    _text(field.value),
                    field.confidence.value,
                    field.note,
                    field.page or "",
                    field.evidence,
                ])


def write_lines_csv(invoices: list[Invoice], path: Path, delimiter: str = ";") -> None:
    """One row per invoice line, across all documents."""
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(("source",) + LINE_COLUMNS)
        for invoice in invoices:
            number = invoice.number.value or ""
            for index, line in enumerate(invoice.lines, start=1):
                writer.writerow([
                    invoice.source, number, index, line.description,
                    _text(line.quantity), _text(line.unit_price),
                    _text(line.vat_rate), _text(line.net_amount), line.page,
                ])


def _text(value) -> str:
    """Render a value for CSV without inventing anything for a missing one."""
    if value is None:
        return ""
    return str(value)
