"""
Field extraction.

Reads pages produced by a `TextSource` and fills an `Invoice`. Nothing here ever
returns a value it did not read from the document: when a label is absent the
field stays `MISSING`, and when the reading is doubtful it is marked
`UNCERTAIN` with a note saying why.
"""
from __future__ import annotations

from decimal import Decimal

from . import patterns
from .model import Confidence, Field, Invoice, Party
from .sources import Page, Word
from .values import (
    clean, format_nip, nip_checksum_ok, normalise_nip, parse_amount,
    parse_currency, parse_date_detailed,
)


def extract_invoice(pages: list[Page], source_name: str) -> Invoice:
    """Extract every top-level field. Line items are added separately."""
    invoice = Invoice(source=source_name, pages=len(pages))
    all_text = "\n".join(page.text for page in pages)
    lines = [line for page in pages for line in page.lines()]

    invoice.number = _number(lines, pages)
    invoice.issue_date = _date_field(lines, pages, patterns.ISSUE_DATE,
                                     patterns.ISSUE_DATE_FALLBACK, "issue date")
    invoice.due_date = _date_field(lines, pages, patterns.DUE_DATE, [], "due date")
    invoice.currency = _currency(all_text)

    invoice.seller, invoice.buyer = _parties(pages)

    invoice.net_total = _amount_field(lines, pages, patterns.NET_TOTAL, "net total")
    invoice.vat_total = _amount_field(lines, pages, patterns.VAT_TOTAL, "VAT total")
    invoice.gross_total = _amount_field(lines, pages, patterns.GROSS_TOTAL, "gross total")

    return invoice


# ------------------------------------------------------------------- scalar fields


def _number(lines: list[str], pages: list[Page]) -> Field[str]:
    for line in lines:
        captured = patterns.first_match(patterns.NUMBER, line)
        if captured:
            # Strip punctuation a title may leave attached, but keep the slashes
            # and dashes that are part of most invoice numbers.
            value = captured.strip(".,;:")
            return Field.found(value, evidence=clean(line), page=_page_of(pages, line))
    return Field.missing("no invoice number label was found")


def _date_field(lines, pages, primary, fallback, label) -> Field:
    for patterns_list, is_fallback in ((primary, False), (fallback, True)):
        for line in lines:
            captured = patterns.first_match(patterns_list, line)
            if captured is None:
                continue
            value, ambiguous = parse_date_detailed(captured)
            evidence, page = clean(line), _page_of(pages, line)
            if value is None:
                return Field.uncertain(
                    None, f"a {label} label was found but the value was not a date",
                    evidence=evidence, page=page,
                )
            if ambiguous:
                return Field.uncertain(
                    value, "day and month could be swapped; read day-first",
                    evidence=evidence, page=page,
                )
            if is_fallback:
                return Field.uncertain(
                    value, f"no explicit {label}; read from a related label instead",
                    evidence=evidence, page=page,
                )
            return Field.found(value, evidence=evidence, page=page)
    return Field.missing(f"no {label} label was found")


def _amount_field(lines, pages, pattern_list, label) -> Field[Decimal]:
    for line in lines:
        captured = patterns.first_match(pattern_list, line)
        if captured is None:
            continue
        value = parse_amount(captured)
        evidence, page = clean(line), _page_of(pages, line)
        if value is None:
            return Field.uncertain(
                None, f"a {label} label was found but no amount could be read from it",
                evidence=evidence, page=page,
            )
        return Field.found(value, evidence=evidence, page=page)
    return Field.missing(f"no {label} label was found")


def _currency(text: str) -> Field[str]:
    code = parse_currency(text)
    if code is None:
        return Field.missing("no currency symbol or code was found")
    # A document mentioning two currencies is a real risk (bank details in one,
    # amounts in another), so say so rather than silently taking the first.
    codes = {c for c in (parse_currency(line) for line in text.splitlines()) if c}
    if len(codes) > 1:
        return Field.uncertain(
            code, f"more than one currency appears in the document: {', '.join(sorted(codes))}",
        )
    return Field.found(code, evidence=code)


def _page_of(pages: list[Page], line: str) -> int | None:
    for page in pages:
        if line in page.text:
            return page.number
    return None


# ------------------------------------------------------------------------ parties


def _parties(pages: list[Page]) -> tuple[Party, Party]:
    """Split the seller and buyer blocks, which usually sit side by side.

    The two blocks share the same text lines, so they cannot be separated by
    reading the text: `"NIP: 5272514626 NIP: 7010345678"` is one line holding one
    value for each party. The split is done on the x coordinate of each word,
    using the heading positions ("Sprzedawca", "Nabywca") to find the boundary.
    """
    page = pages[0]
    seller = _heading_word(page.words, patterns.SELLER_HEADINGS)
    buyer = _heading_word(page.words, patterns.BUYER_HEADINGS)

    if seller is None or buyer is None or abs(buyer.x0 - seller.x0) < 20:
        # Blocks are stacked, or the headings are missing: fall back to reading
        # the whole page and taking the tax ids in order of appearance.
        return _parties_from_text(page)

    # Bound the block vertically as well as horizontally. Splitting on x alone
    # would sweep in the document title, which sits above the headings and spans
    # both columns, and the item table, which sits below them.
    top = min(seller.top, buyer.top) - 2
    bottom = _block_bottom(page.words, top)

    # The boundary is where the right-hand column starts, not the midpoint
    # between the two headings: a long company name easily runs past the middle
    # of the page, and splitting there would move the end of the seller's name
    # into the buyer's block.
    boundary = max(seller.x0, buyer.x0) - 4
    left = _words_within(page.words, top, bottom, max_x=boundary)
    right = _words_within(page.words, top, bottom, min_x=boundary)
    if seller.x0 > buyer.x0:
        left, right = right, left

    return _party_from_words(left, page.number), _party_from_words(right, page.number)


def _heading_word(words: list[Word], headings: tuple[str, ...]) -> Word | None:
    for word in words:
        if word.text.strip().lower().rstrip(":") in headings:
            return word
    return None


def _block_bottom(words: list[Word], top: float) -> float:
    """Find where the party blocks end: the top of the item table, if present."""
    candidates = [
        word.top for word in words
        if word.top > top
        and patterns.classify_heading(word.text.strip()) == "index"
    ]
    if candidates:
        return min(candidates) - 2
    # No table heading found: keep a generous band, enough for a name, a couple
    # of address lines and a tax id.
    return top + 120


def _words_within(words: list[Word], top: float = float("-inf"),
                  bottom: float = float("inf"), min_x: float = float("-inf"),
                  max_x: float = float("inf")) -> list[Word]:
    return [w for w in words if min_x <= w.x0 < max_x and top <= w.top < bottom]


def _party_from_words(words: list[Word], page: int) -> Party:
    """Rebuild the text of one column and read the party out of it."""
    rows: dict[int, list[Word]] = {}
    for word in words:
        # Group words into visual lines: anything within 3 points vertically.
        key = next((k for k in rows if abs(k - word.top) <= 3), round(word.top))
        rows.setdefault(key, []).append(word)

    lines = [
        " ".join(w.text for w in sorted(group, key=lambda w: w.x0))
        for _, group in sorted(rows.items())
    ]
    return _party_from_lines(lines, page)


def _party_from_lines(lines: list[str], page: int) -> Party:
    party = Party()
    body = [clean(line) for line in lines if clean(line)]

    # Drop the heading itself, then the first remaining line is the name.
    headings = patterns.SELLER_HEADINGS + patterns.BUYER_HEADINGS
    body = [line for line in body if line.lower().rstrip(":") not in headings]

    tax_line = next((line for line in body if patterns.TAX_ID.search(line)), None)
    if tax_line:
        party.tax_id = _tax_id(tax_line, page)
        body = [line for line in body if line != tax_line]

    if body:
        party.name = Field.found(body[0], evidence=body[0], page=page)
        if len(body) > 1:
            address = ", ".join(body[1:])
            party.address = Field.found(address, evidence=address, page=page)
        else:
            party.address = Field.missing("no address lines were found")
    else:
        party.name = Field.missing("no name line was found")
    return party


def _tax_id(line: str, page: int) -> Field[str]:
    match = patterns.TAX_ID.search(line)
    if not match:
        return Field.missing("no tax id label was found")
    digits = normalise_nip(match.group(1))
    if digits is None:
        return Field.uncertain(
            clean(match.group(1)), "a tax id label was found but not 10 digits",
            evidence=clean(line), page=page,
        )
    formatted = format_nip(digits)
    if not nip_checksum_ok(digits):
        # A NIP carries a modulo-11 control digit. Failing it means a typo or a
        # misread, so the value is passed through but flagged.
        return Field.uncertain(
            formatted, "the NIP control digit does not check out",
            evidence=clean(line), page=page,
        )
    return Field.found(formatted, evidence=clean(line), page=page)


def _parties_from_text(page: Page) -> tuple[Party, Party]:
    """Fallback when the two blocks cannot be separated by position."""
    lines = [clean(line) for line in page.lines() if clean(line)]
    seller_at = _heading_index(lines, patterns.SELLER_HEADINGS)
    buyer_at = _heading_index(lines, patterns.BUYER_HEADINGS)

    if seller_at is None or buyer_at is None:
        empty = Party(
            name=Field.missing("seller and buyer blocks could not be located"),
            tax_id=Field.missing("seller and buyer blocks could not be located"),
            address=Field.missing("seller and buyer blocks could not be located"),
        )
        return empty, Party(
            name=Field.missing("seller and buyer blocks could not be located"),
            tax_id=Field.missing("seller and buyer blocks could not be located"),
            address=Field.missing("seller and buyer blocks could not be located"),
        )

    first, second = sorted((seller_at, buyer_at))
    block_one = lines[first + 1:second][:5]
    block_two = lines[second + 1:second + 6]
    party_one = _party_from_lines(block_one, page.number)
    party_two = _party_from_lines(block_two, page.number)
    return (party_one, party_two) if seller_at < buyer_at else (party_two, party_one)


def _heading_index(lines: list[str], headings: tuple[str, ...]) -> int | None:
    for index, line in enumerate(lines):
        if line.lower().rstrip(":") in headings:
            return index
    return None
