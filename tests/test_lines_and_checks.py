"""Tests for line-item extraction and the consistency checks."""
from decimal import Decimal

from doc_extractor.model import (
    Confidence, Field, Invoice, Level, LineItem,
)
from doc_extractor.validate import run_checks


# ---------------------------------------------------------------- line items


def test_lines_of_the_simple_invoice(extracted):
    lines = extracted["invoice_pl_simple"].lines

    assert len(lines) == 3
    assert lines[0].description.startswith("Usługa programistyczna")
    assert lines[0].net_amount == Decimal("4500.00")
    assert lines[1].quantity == Decimal("6")
    assert lines[2].unit_price == Decimal("60.00")


def test_a_description_containing_a_number_is_not_split(extracted):
    # "Hosting aplikacji (12 miesięcy)" holds a number inside the description,
    # which the numeric columns must not swallow.
    line = extracted["invoice_pl_simple"].lines[2]

    assert "12 miesięcy" in line.description
    assert line.quantity == Decimal("12")
    assert line.net_amount == Decimal("720.00")


def test_lines_continue_across_a_page_break(extracted):
    invoice = extracted["invoice_pl_multipage"]

    assert len(invoice.lines) == 18
    assert {line.page for line in invoice.lines} == {1, 2}
    assert sum((l.net_amount for l in invoice.lines), Decimal(0)) == Decimal("17100.00")


def test_several_vat_rates_including_an_exempt_line(extracted):
    rates = [line.vat_rate for line in extracted["invoice_pl_multirate"].lines]

    assert rates == [Decimal(23), Decimal(8), Decimal(0)]


def test_negative_line_amounts_on_a_credit_note(extracted):
    lines = extracted["invoice_pl_correction"].lines

    assert all(line.net_amount < 0 for line in lines)
    assert lines[0].net_amount == Decimal("-1200.00")


def test_thousands_separated_amounts_are_read_as_one_number(extracted):
    # "4 500,00" is two tokens in the text layer and must not become 4 and 500.
    assert extracted["invoice_pl_simple"].lines[0].unit_price == Decimal("4500.00")


def test_totals_row_is_not_read_as_a_line_item(extracted):
    descriptions = [l.description.lower() for l in extracted["invoice_pl_simple"].lines]

    assert not any(d.startswith("razem") for d in descriptions)


# ------------------------------------------------------------------- checks


def build(net, vat, gross, lines=(), issue=None, due=None) -> Invoice:
    invoice = Invoice(source="test.pdf", pages=1)
    invoice.net_total = Field.found(net) if net is not None else Field.missing("x")
    invoice.vat_total = Field.found(vat) if vat is not None else Field.missing("x")
    invoice.gross_total = Field.found(gross) if gross is not None else Field.missing("x")
    invoice.lines = list(lines)
    if issue:
        invoice.issue_date = Field.found(issue)
    if due:
        invoice.due_date = Field.found(due)
    return invoice


def result(findings, check):
    return next(f for f in findings if f.check == check)


def test_lines_that_match_the_net_total_are_reported_as_consistent():
    invoice = build(Decimal("300"), Decimal("69"), Decimal("369"), [
        LineItem(description="a", net_amount=Decimal("200")),
        LineItem(description="b", net_amount=Decimal("100")),
    ])

    assert result(run_checks(invoice), "lines_sum").level is Level.OK


def test_lines_that_do_not_match_the_net_total_are_an_error_with_both_numbers():
    invoice = build(Decimal("1600"), Decimal("345"), Decimal("1945"), [
        LineItem(description="a", net_amount=Decimal("1000")),
        LineItem(description="b", net_amount=Decimal("500")),
    ])

    finding = result(run_checks(invoice), "lines_sum")
    assert finding.level is Level.ERROR
    assert finding.expected == Decimal("1500")
    assert finding.actual == Decimal("1600")
    assert finding.difference == Decimal("100")


def test_net_plus_vat_must_equal_gross():
    invoice = build(Decimal("1000"), Decimal("230"), Decimal("1200"))

    finding = result(run_checks(invoice), "net_plus_vat")
    assert finding.level is Level.ERROR
    assert finding.expected == Decimal("1230")


def test_a_missing_total_makes_the_check_incomplete_not_failed():
    invoice = build(Decimal("1000"), None, Decimal("1230"))

    finding = result(run_checks(invoice), "net_plus_vat")
    assert finding.level is Level.WARNING
    assert "VAT" in finding.message


def test_vat_is_recomputed_from_the_per_line_rates():
    invoice = build(Decimal("2850"), Decimal("588"), Decimal("3438"), [
        LineItem(description="a", net_amount=Decimal("2400"), vat_rate=Decimal(23)),
        LineItem(description="b", net_amount=Decimal("450"), vat_rate=Decimal(8)),
    ])

    finding = result(run_checks(invoice), "vat_from_rates")
    assert finding.level is Level.OK
    assert finding.expected == Decimal("588.00")


def test_recomputed_vat_that_disagrees_is_an_error():
    invoice = build(Decimal("1000"), Decimal("100"), Decimal("1100"), [
        LineItem(description="a", net_amount=Decimal("1000"), vat_rate=Decimal(23)),
    ])

    assert result(run_checks(invoice), "vat_from_rates").level is Level.ERROR


def test_one_grosz_of_rounding_is_tolerated_on_the_recomputed_vat():
    # Per-line rounding legitimately drifts by a grosz; a hard equality here
    # would raise an error on perfectly correct invoices.
    invoice = build(Decimal("100.01"), Decimal("23.00"), Decimal("123.01"), [
        LineItem(description="a", net_amount=Decimal("100.01"), vat_rate=Decimal(23)),
    ])

    assert result(run_checks(invoice), "vat_from_rates").level is Level.OK


def test_skipped_rows_prevent_a_false_mismatch():
    # If a row could not be read, the sum is necessarily short. Reporting that as
    # an arithmetic error would blame the invoice for the extractor's failure.
    invoice = build(Decimal("1500"), Decimal("345"), Decimal("1845"), [
        LineItem(description="a", net_amount=Decimal("1000")),
    ])

    finding = result(run_checks(invoice, skipped_rows=1), "lines_sum")
    assert finding.level is Level.WARNING
    assert "could not be read" in finding.message


def test_a_due_date_before_the_issue_date_is_a_warning():
    from datetime import date

    invoice = build(Decimal("100"), Decimal("23"), Decimal("123"),
                    issue=date(2026, 5, 10), due=date(2026, 5, 1))

    assert result(run_checks(invoice), "date_order").level is Level.WARNING


def test_all_negative_totals_are_recognised_as_a_credit_note():
    invoice = build(Decimal("-1700"), Decimal("-391"), Decimal("-2091"))

    finding = result(run_checks(invoice), "sign_consistency")
    assert finding.level is Level.OK
    assert "credit note" in finding.message


def test_mixed_signs_are_flagged():
    invoice = build(Decimal("-1700"), Decimal("391"), Decimal("-1309"))

    assert result(run_checks(invoice), "sign_consistency").level is Level.WARNING


def test_checks_never_modify_the_invoice():
    invoice = build(Decimal("1600"), Decimal("345"), Decimal("1900"), [
        LineItem(description="a", net_amount=Decimal("1000")),
        LineItem(description="b", net_amount=Decimal("500")),
    ])

    run_checks(invoice)

    assert invoice.net_total.value == Decimal("1600"), "a mismatch must not be corrected"
    assert invoice.gross_total.value == Decimal("1900")


def test_the_sample_invoices_that_should_add_up_do(extracted):
    for name in ("invoice_pl_simple", "invoice_pl_multirate",
                 "invoice_pl_correction", "invoice_pl_multipage", "invoice_en_eur"):
        assert not extracted[name].has_errors(), f"{name} should be consistent"


def test_the_deliberately_broken_invoice_is_caught(extracted):
    invoice = extracted["invoice_pl_inconsistent"]
    failed = {f.check for f in invoice.findings if f.level is Level.ERROR}

    assert failed == {"lines_sum", "net_plus_vat"}
