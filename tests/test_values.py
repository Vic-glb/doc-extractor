"""Tests for date, amount and tax-id parsing."""
from datetime import date
from decimal import Decimal

import pytest

from doc_extractor.values import (
    format_nip, nip_checksum_ok, normalise_nip, parse_amount, parse_currency,
    parse_date, parse_date_detailed, parse_percentage,
)


# ------------------------------------------------------------------------ dates


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-03-05", date(2026, 3, 5)),
        ("05.03.2026", date(2026, 3, 5)),
        ("05/03/2026", date(2026, 3, 5)),
        ("31.12.2026", date(2026, 12, 31)),
        ("12 kwietnia 2026", date(2026, 4, 12)),
        ("1 września 2026", date(2026, 9, 1)),
        ("5 pazdziernika 2026", date(2026, 10, 5)),   # written without diacritics
    ],
)
def test_dates_in_polish_and_international_formats(raw, expected):
    assert parse_date(raw) == expected


def test_date_is_read_from_inside_a_label_line():
    assert parse_date("Data wystawienia: 05.03.2026") == date(2026, 3, 5)


def test_ambiguous_day_month_order_is_flagged():
    value, ambiguous = parse_date_detailed("03.07.2026")
    assert value == date(2026, 7, 3), "day-first is the Polish convention"
    assert ambiguous is True


def test_unambiguous_date_is_not_flagged():
    _, ambiguous = parse_date_detailed("25.12.2026")
    assert ambiguous is False


def test_identical_readings_are_not_flagged():
    _, ambiguous = parse_date_detailed("05.05.2026")
    assert ambiguous is False


@pytest.mark.parametrize("raw", ["", "brak", "32.13.2026", "not a date"])
def test_unreadable_dates_return_none(raw):
    assert parse_date(raw) is None


# ---------------------------------------------------------------------- amounts


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1 234,56", Decimal("1234.56")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("4 500,00 PLN", Decimal("4500.00")),
        ("8 265,60 zł", Decimal("8265.60")),
        ("-1 200,00", Decimal("-1200.00")),
        ("(150,00)", Decimal("-150.00")),
        ("1 234,56", Decimal("1234.56")),   # non-breaking space
    ],
)
def test_amounts_in_every_convention(raw, expected):
    assert parse_amount(raw) == expected


def test_amount_keeps_its_decimals():
    assert str(parse_amount("6 720,00")) == "6720.00"


def test_amount_is_read_from_a_totals_line():
    assert parse_amount("Razem brutto 8 265,60 PLN") == Decimal("8265.60")


@pytest.mark.parametrize("raw", ["", "do ustalenia", "brak"])
def test_unreadable_amounts_return_none(raw):
    assert parse_amount(raw) is None


# -------------------------------------------------------------------- currency


@pytest.mark.parametrize(
    "raw,code",
    [("8 265,60 PLN", "PLN"), ("100 zł", "PLN"), ("50 EUR", "EUR"), ("€ 20", "EUR")],
)
def test_currency_codes_are_recognised(raw, code):
    assert parse_currency(raw) == code


def test_no_currency_returns_none():
    assert parse_currency("1234,56") is None


# ------------------------------------------------------------------ percentages


@pytest.mark.parametrize(
    "raw,expected",
    [("23%", Decimal(23)), ("8", Decimal(8)), ("0%", Decimal(0))],
)
def test_vat_rates_are_parsed(raw, expected):
    assert parse_percentage(raw) == expected


@pytest.mark.parametrize("raw", ["zw.", "zw", "np.", "NP"])
def test_polish_vat_exemption_markers_count_as_zero(raw):
    # "zw." (zwolniony) and "np." (nie podlega) are exemptions; arithmetically
    # they contribute no VAT, which is what the checks need.
    assert parse_percentage(raw) == Decimal(0)


# ------------------------------------------------------------------------- NIP


def test_valid_nip_passes_the_checksum():
    # Generated for the samples with the official weights; see samples/make_invoices.py.
    assert nip_checksum_ok("5272514626") is True
    assert nip_checksum_ok("7010345678") is True


def test_wrong_control_digit_fails():
    assert nip_checksum_ok("5272514627") is False


def test_nip_is_read_through_separators_and_a_country_prefix():
    assert normalise_nip("527-251-46-26") == "5272514626"
    assert normalise_nip("PL 527 251 46 26") == "5272514626"


def test_nip_of_the_wrong_length_is_rejected():
    assert normalise_nip("52725146") is None
    assert nip_checksum_ok("52725146") is False


def test_nip_is_formatted_in_the_usual_groups():
    assert format_nip("5272514626") == "527-251-46-26"
