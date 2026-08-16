"""
Parsing of the value types that appear on an invoice: dates, amounts, tax ids.

Same discipline as everywhere else in this tool: these functions return None
rather than a fallback, and never raise on unexpected input.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

_ODD_SPACES = "    "

#: Polish month names in the genitive, which is the form used in dates.
_PL_MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "wrzesnia": 9, "października": 10,
    "pazdziernika": 10, "listopada": 11, "grudnia": 12,
}

_CURRENCY_SYMBOLS = {
    "zł": "PLN", "zl": "PLN", "pln": "PLN",
    "€": "EUR", "eur": "EUR",
    "$": "USD", "usd": "USD",
    "£": "GBP", "gbp": "GBP",
}

_AMOUNT_TEXT = re.compile(r"-?\(?\s*\d[\d\s  .,]*\)?")


def clean(text: str) -> str:
    """Collapse odd spaces and normalise Unicode."""
    for character in _ODD_SPACES:
        text = text.replace(character, " ")
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------------------------ dates


def parse_date(raw: str) -> date | None:
    """Parse a date in the formats that appear on Polish and international invoices.

    Recognises `2026-01-05`, `05.01.2026`, `05/01/2026`, `5 stycznia 2026`.

    Ambiguity is resolved day-first, which is correct for Polish and European
    invoices; `parse_date` reports nothing about that choice, so callers that
    care use `parse_date_detailed`.
    """
    parsed, _ = parse_date_detailed(raw)
    return parsed


def parse_date_detailed(raw: str) -> tuple[date | None, bool]:
    """Parse a date and say whether the day/month order was ambiguous.

    Returns:
        `(value, ambiguous)`. `ambiguous` is True when both readings of the
        digits were valid calendar dates and differed, meaning the day-first
        choice could be wrong.
    """
    text = clean(raw)
    if not text:
        return None, False

    words = re.split(r"[\s.]+", text.lower())
    for index, word in enumerate(words):
        month = _PL_MONTHS.get(word)
        if month and index >= 1:
            day = re.sub(r"\D", "", words[index - 1])
            year = re.sub(r"\D", "", words[index + 1]) if index + 1 < len(words) else ""
            built = _build(year, str(month), day)
            if built:
                return built, False

    match = re.search(r"(\d{1,4})[-./](\d{1,2})[-./](\d{2,4})", text)
    if not match:
        return None, False
    a, b, c = match.groups()

    if len(a) == 4:
        return _build(a, b, c), False

    dayfirst = _build(c, b, a)
    monthfirst = _build(c, a, b)
    if dayfirst and monthfirst and dayfirst != monthfirst:
        return dayfirst, True
    return (dayfirst or monthfirst), False


def _build(year: str, month: str, day: str) -> date | None:
    try:
        y, m, d = int(year), int(month), int(day)
    except ValueError:
        return None
    if len(year) <= 2:
        y += 2000 if y < 70 else 1900
    try:
        return date(y, m, d)
    except ValueError:
        return None


# ---------------------------------------------------------------------- amounts


def parse_amount(raw: str) -> Decimal | None:
    """Parse a monetary amount written in any convention found on invoices.

    Handles `1 234,56`, `1.234,56`, `1,234.56`, `1234.56`, non-breaking spaces,
    a leading or trailing currency, a leading minus, and accounting negatives
    written in parentheses — the latter matter because credit notes (*faktura
    korygująca*) carry negative amounts.
    """
    text = clean(raw)
    if not text:
        return None

    negative = text.startswith("-")
    if negative:
        text = text[1:].strip()

    match = _AMOUNT_TEXT.search(text)
    if not match:
        return None
    token = match.group(0).strip()

    if token.startswith("(") or token.endswith(")"):
        negative = True
        token = token.strip("()").strip()
    if token.startswith("-"):
        negative = True
        token = token[1:]

    token = token.replace(" ", "")
    if not token or not re.fullmatch(r"[\d.,]+", token):
        return None

    has_comma, has_dot = "," in token, "." in token
    if has_comma and has_dot:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif has_comma:
        token = _one_separator(token, ",")
    elif has_dot:
        token = _one_separator(token, ".")

    try:
        value = Decimal(token)
    except InvalidOperation:
        return None
    return -value if negative else value


def _one_separator(token: str, separator: str) -> str:
    head, _, tail = token.rpartition(separator)
    if separator in head:
        return token.replace(separator, "")
    # On an invoice a two-decimal tail is overwhelmingly the decimal part, and a
    # three-digit tail is a thousands group.
    if len(tail) == 3 and head:
        return token.replace(separator, "")
    return token.replace(separator, ".")


def parse_currency(raw: str) -> str | None:
    """Return an ISO currency code found in the text, or None."""
    lowered = clean(raw).lower()
    for token, code in _CURRENCY_SYMBOLS.items():
        if token in lowered:
            return code
    return None


def parse_percentage(raw: str) -> Decimal | None:
    """Parse a VAT rate. `23%`, `23`, `8`, `0`, or `zw` / `np` for exempt.

    Exempt markers return 0, which is what they mean arithmetically, and the
    caller can still see the original text in the raw row.
    """
    text = clean(raw).lower()
    if not text:
        return None
    if text.strip(" %") in ("zw", "zw.", "np", "np.", "oo"):
        return Decimal(0)
    return parse_amount(text.replace("%", ""))


# ----------------------------------------------------------------------- tax id


def normalise_nip(raw: str) -> str | None:
    """Return the 10 digits of a Polish NIP, or None if there are not exactly 10."""
    digits = re.sub(r"\D", "", clean(raw))
    if digits.startswith("PL") or len(digits) != 10:
        digits = re.sub(r"\D", "", clean(raw).upper().removeprefix("PL"))
    return digits if len(digits) == 10 else None


def nip_checksum_ok(nip: str) -> bool:
    """Check the Polish NIP control digit.

    The last digit is a weighted modulo-11 checksum of the first nine, with
    weights 6, 5, 7, 2, 3, 4, 5, 6, 7. A remainder of 10 makes the number
    invalid; no NIP is ever issued in that case.

    This is what lets the tool say "this tax id looks wrong" instead of copying
    a typo into the output as if it were fine.
    """
    digits = normalise_nip(nip)
    if digits is None:
        return False
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    total = sum(int(d) * w for d, w in zip(digits[:9], weights))
    control = total % 11
    if control == 10:
        return False
    return control == int(digits[9])


def format_nip(nip: str) -> str:
    """Render a NIP in the usual grouped form, e.g. 123-456-32-18."""
    digits = normalise_nip(nip)
    if digits is None:
        return nip
    return f"{digits[0:3]}-{digits[3:6]}-{digits[6:8]}-{digits[8:10]}"
