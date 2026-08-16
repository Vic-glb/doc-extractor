"""
Console rendering.

Written to be readable by someone who did not write the code: the confidence of
each field is spelled out, and the arithmetic checks are stated as sentences with
the numbers in them, so a reader can verify the conclusion by hand.
"""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .model import Confidence, Invoice, Level

_CONFIDENCE_STYLE = {
    Confidence.FOUND: "green",
    Confidence.UNCERTAIN: "yellow",
    Confidence.MISSING: "#5FA8FF",
}
_CONFIDENCE_LABEL = {
    Confidence.FOUND: "found",
    Confidence.UNCERTAIN: "check this",
    Confidence.MISSING: "not found",
}

_LEVEL_STYLE = {Level.OK: "green", Level.WARNING: "yellow", Level.ERROR: "#5FA8FF"}
_LEVEL_LABEL = {Level.OK: "consistent", Level.WARNING: "incomplete", Level.ERROR: "does not add up"}

_FIELD_LABELS = {
    "number": "Invoice number",
    "issue_date": "Issue date",
    "due_date": "Due date",
    "currency": "Currency",
    "seller_name": "Seller",
    "seller_tax_id": "Seller tax id",
    "buyer_name": "Buyer",
    "buyer_tax_id": "Buyer tax id",
    "net_total": "Net total",
    "vat_total": "VAT total",
    "gross_total": "Gross total",
}


def render_invoice(invoice: Invoice, console: Console, show_lines: bool = True) -> None:
    """Print one extracted invoice: fields, line items, then the checks."""
    console.print(Panel(
        Text(invoice.source, style="bold"),
        subtitle=f"{invoice.pages} page(s)", border_style="cyan", expand=False,
    ))

    fields = Table(header_style="bold", border_style="grey37", show_lines=False)
    fields.add_column("Field", no_wrap=True)
    fields.add_column("Value", overflow="fold")
    fields.add_column("Status", no_wrap=True)
    fields.add_column("Note", overflow="fold")

    for name, field in invoice.all_fields().items():
        value = "" if field.value is None else str(field.value)
        fields.add_row(
            _FIELD_LABELS.get(name, name),
            value or Text("—", style="dim"),
            Text(_CONFIDENCE_LABEL[field.confidence], style=_CONFIDENCE_STYLE[field.confidence]),
            field.note,
        )
    console.print(fields)

    if show_lines and invoice.lines:
        console.print()
        items = Table(title="Line items", header_style="bold", border_style="grey37")
        items.add_column("#", justify="right", no_wrap=True)
        items.add_column("Description", overflow="fold", max_width=44)
        items.add_column("Qty", justify="right", no_wrap=True)
        items.add_column("Unit price", justify="right", no_wrap=True)
        items.add_column("VAT", justify="right", no_wrap=True)
        items.add_column("Net", justify="right", no_wrap=True)
        for index, line in enumerate(invoice.lines, start=1):
            items.add_row(
                str(index), line.description,
                _number(line.quantity), _number(line.unit_price),
                "" if line.vat_rate is None else f"{line.vat_rate.normalize()}%",
                _number(line.net_amount),
            )
        console.print(items)

    console.print()
    checks = Table(title="Consistency checks", header_style="bold", border_style="grey37")
    checks.add_column("Check", no_wrap=True)
    checks.add_column("Result", no_wrap=True)
    checks.add_column("What it means", overflow="fold")
    for finding in invoice.findings:
        checks.add_row(
            finding.check,
            Text(_LEVEL_LABEL[finding.level], style=_LEVEL_STYLE[finding.level]),
            finding.message,
        )
    console.print(checks)


def render_summary(invoices: list[Invoice], console: Console) -> None:
    """Print one line per document, for a run over several files."""
    table = Table(title="Summary", header_style="bold", border_style="grey37")
    table.add_column("Document", overflow="fold")
    table.add_column("Number", no_wrap=True)
    table.add_column("Gross", justify="right", no_wrap=True)
    table.add_column("Lines", justify="right", no_wrap=True)
    table.add_column("To check", justify="right", no_wrap=True)
    table.add_column("Arithmetic", no_wrap=True)

    for invoice in invoices:
        errors = [f for f in invoice.findings if f.level is Level.ERROR]
        review = len(invoice.fields_needing_review())
        table.add_row(
            invoice.source,
            invoice.number.value or Text("—", style="dim"),
            _number(invoice.gross_total.value),
            str(len(invoice.lines)),
            Text(str(review), style="yellow" if review else "green"),
            Text("does not add up", style="#5FA8FF") if errors
            else Text("consistent", style="green"),
        )
    console.print(table)


def _number(value) -> str:
    return "" if value is None else f"{value:,.2f}".replace(",", " ")
