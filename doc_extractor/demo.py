"""
The `demo` command.

Runs the extractor over the bundled sample invoices and prints two tables meant
to be read at a glance, and to photograph well:

  1. a field-by-document matrix showing the status of every field, which makes
     the "never guessed" rule visible — a value is found, flagged, or absent;
  2. the arithmetic checks with the expected value, the stated value and the
     difference between them.

This writes nothing and adds no capability: it is the existing extraction and
the existing checks, laid out for reading.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .model import Confidence, Invoice, Level

#: Symbol and colour per confidence, for the compact matrix.
_MARK = {
    Confidence.FOUND: ("found", "#3FB950"),
    Confidence.UNCERTAIN: ("check this", "#D29922"),
    Confidence.MISSING: ("not found", "#5FA8FF"),
}

_FIELD_ORDER = [
    ("number", "Invoice number"),
    ("issue_date", "Issue date"),
    ("due_date", "Due date"),
    ("currency", "Currency"),
    ("seller_name", "Seller"),
    ("seller_tax_id", "Seller NIP"),
    ("buyer_name", "Buyer"),
    ("buyer_tax_id", "Buyer NIP"),
    ("net_total", "Net total"),
    ("vat_total", "VAT total"),
    ("gross_total", "Gross total"),
]

#: Short column headers, so six documents fit side by side.
_SHORT = {
    "invoice_pl_simple.pdf": "simple",
    "invoice_pl_multirate.pdf": "multi-rate",
    "invoice_pl_correction.pdf": "credit note",
    "invoice_pl_multipage.pdf": "2 pages",
    "invoice_en_eur.pdf": "EN / EUR",
    "invoice_pl_inconsistent.pdf": "broken",
}


def sample_paths(samples: Path) -> list[Path]:
    """The bundled invoices, in a deliberate order: working ones first."""
    order = list(_SHORT)
    found = {path.name: path for path in samples.glob("invoice_*.pdf")}
    ordered = [found[name] for name in order if name in found]
    ordered += [path for name, path in sorted(found.items()) if name not in order]
    return ordered


def render_field_matrix(invoices: list[Invoice], console: Console) -> None:
    """One row per field, one column per document."""
    table = Table(
        title="Every field, and how sure the extractor is",
        header_style="bold", border_style="grey37",
    )
    table.add_column("Field", no_wrap=True)
    for invoice in invoices:
        table.add_column(_SHORT.get(invoice.source, invoice.source), no_wrap=True, justify="center")

    for key, label in _FIELD_ORDER:
        cells = []
        for invoice in invoices:
            field = invoice.all_fields().get(key)
            if field is None:
                cells.append(Text("—", style="dim"))
                continue
            text, style = _MARK[field.confidence]
            cells.append(Text(text, style=style))
        table.add_row(label, *cells)

    console.print(table)
    console.print(
        "[dim]A field is never guessed: it is either read from the document, flagged for "
        "a human, or reported as absent.[/dim]"
    )


def render_arithmetic(invoices: list[Invoice], console: Console) -> None:
    """The consistency checks, with the gap between expected and stated."""
    table = Table(
        title="Does the invoice agree with itself?",
        header_style="bold", border_style="grey37",
    )
    table.add_column("Document", no_wrap=True)
    table.add_column("Check", no_wrap=True)
    table.add_column("Computed", justify="right", no_wrap=True)
    table.add_column("Stated", justify="right", no_wrap=True)
    table.add_column("Difference", justify="right", no_wrap=True)
    table.add_column("Result", no_wrap=True)

    for invoice in invoices:
        shown = 0
        for finding in invoice.findings:
            # Only the checks that actually compared two numbers carry a gap.
            if finding.expected is None or finding.actual is None:
                continue
            difference = finding.difference or Decimal(0)
            style = {
                Level.OK: "#3FB950", Level.WARNING: "#D29922", Level.ERROR: "#5FA8FF",
            }[finding.level]
            label = {
                Level.OK: "matches", Level.WARNING: "incomplete", Level.ERROR: "does not add up",
            }[finding.level]
            table.add_row(
                _SHORT.get(invoice.source, invoice.source) if shown == 0 else "",
                finding.check,
                _money(finding.expected),
                _money(finding.actual),
                Text(_money(difference) if difference else "0.00",
                     style="#5FA8FF" if difference else "#3FB950"),
                Text(label, style=style),
            )
            shown += 1
        if shown:
            table.add_section()

    console.print(table)


def render_notes(invoices: list[Invoice], console: Console) -> None:
    """Spell out every flagged field, since the matrix only shows the status."""
    flagged = [
        (invoice, name, field)
        for invoice in invoices
        for name, field in invoice.all_fields().items()
        if field.confidence is Confidence.UNCERTAIN
    ]
    if not flagged:
        return

    table = Table(title="What was flagged, and why", header_style="bold", border_style="grey37")
    table.add_column("Document", no_wrap=True)
    table.add_column("Field", no_wrap=True)
    table.add_column("Value kept", no_wrap=True)
    table.add_column("Reason", overflow="fold")

    labels = dict(_FIELD_ORDER)
    for invoice, name, field in flagged:
        table.add_row(
            _SHORT.get(invoice.source, invoice.source),
            labels.get(name, name),
            "" if field.value is None else str(field.value),
            field.note,
        )
    console.print(table)


def _money(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ")
