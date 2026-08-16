"""Tests for field extraction against the generated sample invoices."""
from datetime import date
from decimal import Decimal

import pytest

from doc_extractor.model import Confidence
from doc_extractor.sources import EmptyTextLayer, PdfTextSource


# ------------------------------------------------------------------ text source


def test_a_pdf_without_a_text_layer_is_refused_with_a_clear_reason(scanned_pdf):
    # This is the failure a user is most likely to hit, so it must say "scan"
    # rather than silently returning an invoice with every field missing.
    with pytest.raises(EmptyTextLayer, match="scan"):
        PdfTextSource().read(scanned_pdf)


def test_the_source_only_claims_pdfs(tmp_path):
    source = PdfTextSource()
    assert source.supports(tmp_path / "a.pdf") is True
    assert source.supports(tmp_path / "a.png") is False


def test_words_carry_coordinates(samples):
    # The OCR seam depends on positions being part of the interface, and party
    # splitting depends on them being real.
    pages = PdfTextSource().read(samples / "invoice_pl_simple.pdf")
    word = pages[0].words[0]
    assert word.x1 > word.x0
    assert word.bottom > word.top


# ---------------------------------------------------------------- simple invoice


def test_header_fields_of_the_simple_invoice(extracted):
    invoice = extracted["invoice_pl_simple"]

    assert invoice.number.value == "FV/2026/03/017"
    assert invoice.number.confidence is Confidence.FOUND
    assert invoice.issue_date.value == date(2026, 3, 5)
    assert invoice.due_date.value == date(2026, 3, 19)
    assert invoice.currency.value == "PLN"


def test_totals_of_the_simple_invoice(extracted):
    invoice = extracted["invoice_pl_simple"]

    assert invoice.net_total.value == Decimal("6720.00")
    assert invoice.vat_total.value == Decimal("1545.60")
    assert invoice.gross_total.value == Decimal("8265.60")


def test_seller_and_buyer_are_separated_even_though_they_share_text_lines(extracted):
    # In the PDF, "NIP: 5272514626 NIP: 7010345678" is a single line of text.
    # Splitting has to happen on coordinates, not on the text.
    invoice = extracted["invoice_pl_simple"]

    assert invoice.seller.name.value == "Przykładowa Firma Testowa Sp. z o.o."
    assert invoice.buyer.name.value == "Modelowy Nabywca S.A."
    assert invoice.seller.tax_id.value == "527-251-46-26"
    assert invoice.buyer.tax_id.value == "701-034-56-78"


def test_a_long_company_name_is_not_cut_at_the_middle_of_the_page(extracted):
    # The seller name runs past the horizontal centre of the page; the column
    # boundary is the start of the buyer block, not the midpoint.
    invoice = extracted["invoice_pl_simple"]

    assert invoice.seller.name.value.endswith("Sp. z o.o.")
    assert "Sp. z o.o." not in invoice.buyer.name.value


def test_addresses_are_captured(extracted):
    invoice = extracted["invoice_pl_simple"]

    assert "Wymyślona" in invoice.seller.address.value
    assert "Kraków" in invoice.buyer.address.value


def test_a_valid_tax_id_is_reported_as_found(extracted):
    assert extracted["invoice_pl_simple"].seller.tax_id.confidence is Confidence.FOUND


def test_every_field_carries_the_text_it_was_read_from(extracted):
    invoice = extracted["invoice_pl_simple"]
    for name, field in invoice.all_fields().items():
        if field.confidence is Confidence.FOUND:
            assert field.evidence, f"{name} was found but carries no evidence"


# -------------------------------------------------------------- other documents


def test_polish_month_name_date(extracted):
    assert extracted["invoice_pl_multirate"].issue_date.value == date(2026, 4, 12)


def test_english_labels_and_euros(extracted):
    invoice = extracted["invoice_en_eur"]

    assert invoice.number.value == "INV/2026/06/113"
    assert invoice.issue_date.value == date(2026, 6, 1)
    assert invoice.currency.value == "EUR"
    assert invoice.gross_total.value == Decimal("4674.00")


def test_credit_note_totals_are_negative(extracted):
    invoice = extracted["invoice_pl_correction"]

    assert invoice.number.value == "FK/2026/04/001"
    assert invoice.net_total.value == Decimal("-1700.00")
    assert invoice.gross_total.value == Decimal("-2091.00")


def test_a_broken_tax_id_is_flagged_not_dropped(extracted):
    # The value is still reported — a human may want to see the typo — but it is
    # explicitly marked as failing its control digit.
    field = extracted["invoice_pl_inconsistent"].seller.tax_id

    assert field.confidence is Confidence.UNCERTAIN
    assert "control digit" in field.note
    assert field.value == "527-251-46-27"


def test_multipage_invoice_reads_the_totals_from_the_last_page(extracted):
    invoice = extracted["invoice_pl_multipage"]

    assert invoice.pages == 2
    assert invoice.net_total.value == Decimal("17100.00")


def test_a_missing_field_is_none_and_never_a_plausible_value():
    from doc_extractor.extract import extract_invoice
    from doc_extractor.sources import Page

    invoice = extract_invoice([Page(number=1, text="a document with nothing in it")], "x.pdf")

    for name, field in invoice.all_fields().items():
        assert field.value is None, f"{name} invented {field.value!r}"
        assert field.confidence is Confidence.MISSING
        assert field.note, "a missing field should say why"
