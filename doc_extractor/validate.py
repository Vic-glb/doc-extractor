"""
Arithmetic and consistency checks.

Nothing here ever corrects a value. Each check compares what the document says
against what its own numbers imply, and records a `Finding`. Deciding what to do
about a mismatch belongs to the person reading the invoice, not to this tool: a
silent "fix" would hide exactly the problem worth knowing about.
"""
from __future__ import annotations

from decimal import Decimal

from .model import Finding, Invoice, Level

#: Amounts are compared to the grosz. A one-grosz gap is normal rounding on a
#: per-line VAT calculation, so it is reported as a warning rather than an error;
#: anything larger is a real disagreement.
EXACT = Decimal("0.01")
ROUNDING_TOLERANCE = Decimal("0.02")


def run_checks(invoice: Invoice, skipped_rows: int = 0) -> list[Finding]:
    """Run every check and return the findings, most severe first."""
    findings: list[Finding] = []

    findings.extend(_lines_sum_to_net(invoice, skipped_rows))
    findings.extend(_net_plus_vat_is_gross(invoice))
    findings.extend(_vat_matches_rates(invoice))
    findings.extend(_dates_are_ordered(invoice))
    findings.extend(_sign_consistency(invoice))

    order = {Level.ERROR: 0, Level.WARNING: 1, Level.OK: 2}
    return sorted(findings, key=lambda f: order[f.level])


def _lines_sum_to_net(invoice: Invoice, skipped_rows: int) -> list[Finding]:
    if not invoice.lines:
        return [Finding("lines_sum", Level.WARNING,
                        "No line items were found, so the net total could not be cross-checked.")]
    if skipped_rows:
        return [Finding("lines_sum", Level.WARNING,
                        f"{skipped_rows} table row(s) could not be read, so the sum of the "
                        "lines cannot be compared with the net total.")]

    amounts = [line.net_amount for line in invoice.lines if line.net_amount is not None]
    if len(amounts) != len(invoice.lines):
        return [Finding("lines_sum", Level.WARNING,
                        "Some lines have no readable amount, so the sum was not compared.")]

    total = sum(amounts, Decimal(0))
    if invoice.net_total.value is None:
        return [Finding("lines_sum", Level.WARNING,
                        f"The lines add up to {total}, but no net total was found to compare it with.",
                        expected=total)]

    difference = abs(total - invoice.net_total.value)
    if difference <= EXACT:
        return [Finding("lines_sum", Level.OK,
                        f"The {len(amounts)} lines add up to the net total ({total}).",
                        expected=total, actual=invoice.net_total.value)]
    return [Finding("lines_sum", Level.ERROR,
                    f"The lines add up to {total}, but the invoice states a net total of "
                    f"{invoice.net_total.value}.",
                    expected=total, actual=invoice.net_total.value)]


def _net_plus_vat_is_gross(invoice: Invoice) -> list[Finding]:
    net, vat, gross = (invoice.net_total.value, invoice.vat_total.value,
                       invoice.gross_total.value)
    if net is None or vat is None or gross is None:
        missing = [name for name, value in
                   (("net", net), ("VAT", vat), ("gross", gross)) if value is None]
        return [Finding("net_plus_vat", Level.WARNING,
                        f"Could not check net + VAT = gross: {', '.join(missing)} not found.")]

    expected = net + vat
    difference = abs(expected - gross)
    if difference <= EXACT:
        return [Finding("net_plus_vat", Level.OK,
                        f"Net plus VAT equals the gross total ({gross}).",
                        expected=expected, actual=gross)]
    return [Finding("net_plus_vat", Level.ERROR,
                    f"Net {net} plus VAT {vat} is {expected}, but the invoice states a gross "
                    f"total of {gross}.", expected=expected, actual=gross)]


def _vat_matches_rates(invoice: Invoice) -> list[Finding]:
    """Recompute VAT from the per-line rates, when every line carries one."""
    usable = [l for l in invoice.lines if l.net_amount is not None and l.vat_rate is not None]
    if not usable or len(usable) != len(invoice.lines):
        return []
    if invoice.vat_total.value is None:
        return []

    computed = sum(
        (line.net_amount * line.vat_rate / Decimal(100) for line in usable), Decimal(0)
    ).quantize(Decimal("0.01"))

    difference = abs(computed - invoice.vat_total.value)
    rates = sorted({line.vat_rate for line in usable})
    label = "rate" if len(rates) == 1 else "rates"
    listed = ", ".join(f"{rate.normalize()}%" for rate in rates)

    if difference <= ROUNDING_TOLERANCE:
        return [Finding("vat_from_rates", Level.OK,
                        f"VAT recomputed from the per-line {label} ({listed}) matches the stated "
                        f"VAT total ({invoice.vat_total.value}).",
                        expected=computed, actual=invoice.vat_total.value)]
    return [Finding("vat_from_rates", Level.ERROR,
                    f"The per-line {label} ({listed}) give a VAT of {computed}, but the invoice "
                    f"states {invoice.vat_total.value}.",
                    expected=computed, actual=invoice.vat_total.value)]


def _dates_are_ordered(invoice: Invoice) -> list[Finding]:
    issue, due = invoice.issue_date.value, invoice.due_date.value
    if issue is None or due is None:
        return []
    if due < issue:
        return [Finding("date_order", Level.WARNING,
                        f"The due date ({due}) is before the issue date ({issue}).")]
    return [Finding("date_order", Level.OK,
                    f"The due date ({due}) is on or after the issue date ({issue}).")]


def _sign_consistency(invoice: Invoice) -> list[Finding]:
    """A credit note is negative throughout; a mix of signs is worth a look."""
    values = [v for v in (invoice.net_total.value, invoice.vat_total.value,
                          invoice.gross_total.value) if v is not None]
    if len(values) < 2:
        return []
    negatives = [v for v in values if v < 0]
    if negatives and len(negatives) != len(values):
        return [Finding("sign_consistency", Level.WARNING,
                        "Some totals are negative and others are positive. On a credit note all "
                        "of them are normally negative.")]
    if negatives:
        return [Finding("sign_consistency", Level.OK,
                        "All totals are negative, consistent with a credit note.")]
    return []
