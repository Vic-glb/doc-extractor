"""
Label patterns.

Polish invoices come first, since that is the market this was written for, but
every label list also carries its English equivalent so a document from an
international supplier still works.

Patterns are kept here, apart from the extraction logic, so that adding support
for a new supplier's wording is a change to a list rather than to code.
"""
from __future__ import annotations

import re

#: Invoice number. The document title usually carries it: "Faktura VAT nr X",
#: "Faktura korygująca nr X", "Invoice No X".
NUMBER = [
    re.compile(r"faktura\s+(?:vat\s+)?(?:koryguj[ąa]ca\s+)?(?:nr|numer)[\s.:]*([^\s]+)", re.I),
    re.compile(r"\b(?:nr|numer)\s+faktury[\s.:]*([^\s]+)", re.I),
    re.compile(r"invoice\s*(?:no\.?|number|#)[\s.:]*([^\s]+)", re.I),
]

#: Issue date. `data sprzedaży` is a different legal date but is the closest
#: available when `data wystawienia` is absent, so it comes last and the caller
#: marks the field uncertain when it had to fall back to it.
ISSUE_DATE = [
    re.compile(r"data\s+wystawienia[\s.:]*(.+)", re.I),
    re.compile(r"issue\s+date[\s.:]*(.+)", re.I),
    re.compile(r"date\s+of\s+issue[\s.:]*(.+)", re.I),
]
ISSUE_DATE_FALLBACK = [
    re.compile(r"data\s+sprzeda[żz]y[\s.:]*(.+)", re.I),
]

DUE_DATE = [
    re.compile(r"termin\s+p[łl]atno[śs]ci[\s.:]*(.+)", re.I),
    re.compile(r"due\s+date[\s.:]*(.+)", re.I),
    re.compile(r"payment\s+due[\s.:]*(.+)", re.I),
]

#: Headings that start the seller / buyer blocks.
SELLER_HEADINGS = ("sprzedawca", "wystawca", "seller", "supplier", "from")
BUYER_HEADINGS = ("nabywca", "kupujący", "kupujacy", "odbiorca", "buyer", "customer", "bill to")

#: Totals. Matched against a whole line, with the amount taken from the tail.
NET_TOTAL = [
    re.compile(r"razem\s+netto[\s.:]*(.+)", re.I),
    re.compile(r"suma\s+netto[\s.:]*(.+)", re.I),
    re.compile(r"warto[śs][ćc]\s+netto[\s.:]*(.+)", re.I),
    re.compile(r"net\s+total[\s.:]*(.+)", re.I),
    re.compile(r"total\s+net[\s.:]*(.+)", re.I),
    re.compile(r"subtotal[\s.:]*(.+)", re.I),
]
VAT_TOTAL = [
    re.compile(r"razem\s+vat[\s.:]*(.+)", re.I),
    re.compile(r"suma\s+vat[\s.:]*(.+)", re.I),
    re.compile(r"kwota\s+vat[\s.:]*(.+)", re.I),
    re.compile(r"vat\s+total[\s.:]*(.+)", re.I),
    re.compile(r"total\s+vat[\s.:]*(.+)", re.I),
    re.compile(r"\btax\b[\s.:]*(.+)", re.I),
]
GROSS_TOTAL = [
    re.compile(r"razem\s+brutto[\s.:]*(.+)", re.I),
    re.compile(r"suma\s+brutto[\s.:]*(.+)", re.I),
    re.compile(r"do\s+zap[łl]aty[\s.:]*(.+)", re.I),
    re.compile(r"gross\s+total[\s.:]*(.+)", re.I),
    re.compile(r"total\s+gross[\s.:]*(.+)", re.I),
    re.compile(r"amount\s+due[\s.:]*(.+)", re.I),
]

#: A tax id, with or without the country prefix and separators.
TAX_ID = re.compile(r"\b(?:NIP|VAT\s*ID|VAT\s*No\.?|Tax\s*ID)[\s.:]*((?:PL)?[\d\s-]{10,17})", re.I)

#: Column headings of the line-item table, used to recognise which column is which.
COLUMN_HEADINGS = {
    "index": ("lp.", "lp", "no.", "no", "#", "poz."),
    "description": ("nazwa", "opis", "towar", "usługa", "usluga", "description", "item"),
    "quantity": ("ilość", "ilosc", "qty", "quantity", "szt"),
    "unit_price": ("cena", "unit price", "price", "cena netto", "cena jedn"),
    "vat_rate": ("vat", "stawka", "vat %", "tax rate"),
    "net_amount": ("wartość", "wartosc", "net amount", "amount", "value", "wartość netto"),
}

#: Words that mark the end of the line-item table.
TABLE_STOP = ("razem", "suma", "do zapłaty", "do zaplaty", "total", "subtotal")


def first_match(patterns: list[re.Pattern], text: str) -> str | None:
    """Return the first capture group matched by any pattern, or None."""
    for pattern in patterns:
        found = pattern.search(text)
        if found:
            captured = found.group(1).strip()
            if captured:
                return captured
    return None


def classify_heading(cell: str) -> str | None:
    """Map a table heading cell to a known column name, or None if unrecognised."""
    lowered = cell.strip().lower()
    if not lowered:
        return None
    for column, keywords in COLUMN_HEADINGS.items():
        for keyword in keywords:
            if lowered == keyword or lowered.startswith(keyword):
                return column
    # "wartość netto" must not be read as "wartość" alone if a better match exists,
    # so containment is only tried after exact and prefix matching have failed.
    for column, keywords in COLUMN_HEADINGS.items():
        if any(keyword in lowered for keyword in keywords):
            return column
    return None
