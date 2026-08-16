"""
Generate the sample invoices.

Everything here is invented: company names, addresses, tax ids, invoice numbers,
descriptions and amounts. None of it refers to a real business or person. The
tax ids are built so their control digit is valid, because a checksum that never
passes would make the checksum test meaningless — except for one invoice which
carries a deliberately broken one.

Run from the project root:

    python samples/make_invoices.py
"""
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

SAMPLES = Path(__file__).parent
WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)

#: Every Polish letter outside ASCII. A font missing any of these silently
#: renders the wrong glyph, which would make these samples a poor stand-in for
#: real Polish invoices — and would quietly train the extractor on broken text.
POLISH_LETTERS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"

#: (regular, bold) candidates, tried in order across macOS, Linux and Windows.
FONT_CANDIDATES = (
    ("/System/Library/Fonts/Supplemental/Verdana.ttf",
     "/System/Library/Fonts/Supplemental/Verdana Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Tahoma.ttf",
     "/System/Library/Fonts/Supplemental/Tahoma Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", None),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
)

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _covers_polish(font) -> bool:
    return all(ord(letter) in font.face.charToGlyph for letter in POLISH_LETTERS)


def register_font() -> bool:
    """Register a font that can actually render Polish. Returns True on success.

    reportlab's built-in Helvetica and its bundled Vera both lack most Polish
    diacritics, and silently substitute other glyphs rather than failing, so the
    coverage is checked explicitly instead of assumed.
    """
    global FONT_REGULAR, FONT_BOLD
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont as PdfTTFont

    for regular_path, bold_path in FONT_CANDIDATES:
        if not Path(regular_path).exists():
            continue
        try:
            regular = PdfTTFont("SampleFont", regular_path)
        except Exception:
            continue
        if not _covers_polish(regular):
            continue

        pdfmetrics.registerFont(regular)
        FONT_REGULAR = "SampleFont"
        FONT_BOLD = "SampleFont"
        if bold_path and Path(bold_path).exists():
            try:
                pdfmetrics.registerFont(PdfTTFont("SampleFont-Bold", bold_path))
                FONT_BOLD = "SampleFont-Bold"
            except Exception:
                pass
        pdfmetrics.registerFontFamily(
            "SampleFont", normal="SampleFont", bold=FONT_BOLD,
            italic="SampleFont", boldItalic=FONT_BOLD,
        )
        return True
    return False


def nip_with_valid_checksum(first_nine: str) -> str:
    """Append the correct control digit to nine digits.

    Raises:
        ValueError: If the nine digits give a remainder of 10, which cannot be a
            valid NIP — pick different digits in that case.
    """
    total = sum(int(d) * w for d, w in zip(first_nine, WEIGHTS))
    control = total % 11
    if control == 10:
        raise ValueError(f"{first_nine} cannot form a valid NIP")
    return first_nine + str(control)


SELLER_NIP = nip_with_valid_checksum("527251462")
BUYER_NIP = nip_with_valid_checksum("701034567")
# Last digit deliberately wrong, to exercise the checksum warning.
BROKEN_NIP = SELLER_NIP[:9] + str((int(SELLER_NIP[9]) + 1) % 10)


def styles():
    sheet = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=sheet["Title"], fontSize=16, spaceAfter=6,
                                fontName=FONT_BOLD),
        "normal": ParagraphStyle("n", parent=sheet["Normal"], fontSize=9, leading=12,
                                 fontName=FONT_REGULAR),
        "small": ParagraphStyle("s", parent=sheet["Normal"], fontSize=8, leading=10,
                                fontName=FONT_REGULAR),
    }


def party_block(label, name, address, nip, style):
    return Paragraph(
        f"<b>{label}</b><br/>{name}<br/>{address}<br/>NIP: {nip}", style
    )


def money(value: Decimal) -> str:
    """Polish formatting: space thousands separator, decimal comma."""
    text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return text


def build_invoice(path: Path, *, title, number, issue_date, due_date, seller_nip,
                  buyer_nip, rows, totals, currency="PLN", english=False,
                  page_break_after=None, footer_note=""):
    """Write one invoice PDF."""
    s = styles()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
    )
    labels = {
        "issued": "Issue date" if english else "Data wystawienia",
        "due": "Due date" if english else "Termin płatności",
        "seller": "Seller" if english else "Sprzedawca",
        "buyer": "Buyer" if english else "Nabywca",
        "net": "Net total" if english else "Razem netto",
        "vat": "VAT total" if english else "Razem VAT",
        "gross": "Gross total" if english else "Razem brutto",
        "tax": "VAT ID" if english else "NIP",
    }
    header = (
        ["No.", "Description", "Qty", "Unit price", "VAT %", "Net amount"] if english
        else ["Lp.", "Nazwa towaru/usługi", "Ilość", "Cena netto", "VAT %", "Wartość netto"]
    )

    story = [Paragraph(title, s["title"])]
    story.append(Paragraph(f"{labels['issued']}: {issue_date}", s["normal"]))
    story.append(Paragraph(f"{labels['due']}: {due_date}", s["normal"]))
    story.append(Spacer(1, 8 * mm))

    parties = Table(
        [[
            party_block(labels["seller"], "Przykładowa Firma Testowa Sp. z o.o.",
                        "ul. Wymyślona 12/3<br/>00-001 Warszawa", seller_nip, s["normal"]),
            party_block(labels["buyer"], "Modelowy Nabywca S.A.",
                        "ul. Fikcyjna 7<br/>30-002 Kraków", buyer_nip, s["normal"]),
        ]],
        colWidths=[85 * mm, 85 * mm],
    )
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(parties)
    story.append(Spacer(1, 8 * mm))

    data = [header]
    for index, row in enumerate(rows, start=1):
        description, quantity, unit_price, vat_rate, net = row
        data.append([
            str(index), description, str(quantity), money(unit_price),
            f"{vat_rate}%" if vat_rate is not None else "zw.", money(net),
        ])
        if page_break_after and index == page_break_after:
            story.append(_table(data))
            story.append(PageBreak())
            data = [header]

    story.append(_table(data))
    story.append(Spacer(1, 6 * mm))

    net_total, vat_total, gross_total = totals
    summary = Table(
        [
            [labels["net"], f"{money(net_total)} {currency}"],
            [labels["vat"], f"{money(vat_total)} {currency}"],
            [labels["gross"], f"{money(gross_total)} {currency}"],
        ],
        colWidths=[45 * mm, 40 * mm], hAlign="RIGHT",
    )
    summary.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
        ("FONTNAME", (0, 2), (-1, 2), FONT_BOLD),
        ("LINEABOVE", (0, 2), (-1, 2), 0.5, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(summary)

    if footer_note:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(footer_note, s["small"]))

    doc.build(story)
    return path


def _table(data):
    table = Table(data, colWidths=[10 * mm, 68 * mm, 15 * mm, 25 * mm, 15 * mm, 28 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.92, 0.92, 0.92)),
        ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def d(value: str) -> Decimal:
    return Decimal(value)


def main():
    if not register_font():
        raise SystemExit(
            "No font with full Polish coverage was found on this machine.\n"
            "Generating the samples with Helvetica would silently replace ą, ł, ś… "
            "with wrong glyphs, making them a bad stand-in for real invoices.\n"
            f"Install one of: {', '.join(path for path, _ in FONT_CANDIDATES)}"
        )
    written = []

    # 1. Straightforward single-rate Polish invoice.
    written.append(build_invoice(
        SAMPLES / "invoice_pl_simple.pdf",
        title="Faktura VAT nr FV/2026/03/017",
        number="FV/2026/03/017",
        issue_date="05.03.2026", due_date="19.03.2026",
        seller_nip=SELLER_NIP, buyer_nip=BUYER_NIP,
        rows=[
            ("Usługa programistyczna - marzec 2026", 1, d("4500.00"), 23, d("4500.00")),
            ("Konsultacje techniczne", 6, d("250.00"), 23, d("1500.00")),
            ("Hosting aplikacji (12 miesięcy)", 12, d("60.00"), 23, d("720.00")),
        ],
        totals=(d("6720.00"), d("1545.60"), d("8265.60")),
    ))

    # 2. Several VAT rates, including an exempt line.
    written.append(build_invoice(
        SAMPLES / "invoice_pl_multirate.pdf",
        title="Faktura VAT nr FV/2026/04/002",
        number="FV/2026/04/002",
        issue_date="12 kwietnia 2026", due_date="26.04.2026",
        seller_nip=SELLER_NIP, buyer_nip=BUYER_NIP,
        rows=[
            ("Licencja oprogramowania", 2, d("1200.00"), 23, d("2400.00")),
            ("Materiały szkoleniowe (książki)", 10, d("45.00"), 8, d("450.00")),
            ("Szkolenie zawodowe", 1, d("2000.00"), None, d("2000.00")),
        ],
        # 2400*0.23 = 552.00 ; 450*0.08 = 36.00 ; exempt = 0
        totals=(d("4850.00"), d("588.00"), d("5438.00")),
    ))

    # 3. Credit note with negative amounts.
    written.append(build_invoice(
        SAMPLES / "invoice_pl_correction.pdf",
        title="Faktura korygująca nr FK/2026/04/001",
        number="FK/2026/04/001",
        issue_date="20.04.2026", due_date="04.05.2026",
        seller_nip=SELLER_NIP, buyer_nip=BUYER_NIP,
        rows=[
            ("Korekta - zwrot licencji", -1, d("1200.00"), 23, d("-1200.00")),
            ("Korekta ceny konsultacji", -2, d("250.00"), 23, d("-500.00")),
        ],
        totals=(d("-1700.00"), d("-391.00"), d("-2091.00")),
        footer_note="Korekta do faktury FV/2026/04/002 z dnia 12.04.2026.",
    ))

    # 4. Two pages of line items.
    many = [
        (f"Pozycja testowa nr {i:02d}", i, d("100.00"), 23, d("100.00") * i)
        for i in range(1, 19)
    ]
    net = sum((row[4] for row in many), Decimal(0))
    written.append(build_invoice(
        SAMPLES / "invoice_pl_multipage.pdf",
        title="Faktura VAT nr FV/2026/05/044",
        number="FV/2026/05/044",
        issue_date="2026-05-04", due_date="2026-05-18",
        seller_nip=SELLER_NIP, buyer_nip=BUYER_NIP,
        rows=many,
        totals=(net, (net * Decimal("0.23")).quantize(Decimal("0.01")),
                (net * Decimal("1.23")).quantize(Decimal("0.01"))),
        page_break_after=11,
    ))

    # 5. English labels, euros, ISO dates.
    written.append(build_invoice(
        SAMPLES / "invoice_en_eur.pdf",
        title="Invoice No INV/2026/06/113",
        number="INV/2026/06/113",
        issue_date="2026-06-01", due_date="2026-06-15",
        seller_nip=SELLER_NIP, buyer_nip=BUYER_NIP,
        rows=[
            ("Software development - May 2026", 1, d("3200.00"), 23, d("3200.00")),
            ("Code review", 4, d("150.00"), 23, d("600.00")),
        ],
        totals=(d("3800.00"), d("874.00"), d("4674.00")),
        currency="EUR", english=True,
    ))

    # 6. Totals that do not add up, and a tax id with a wrong control digit.
    written.append(build_invoice(
        SAMPLES / "invoice_pl_inconsistent.pdf",
        title="Faktura VAT nr FV/2026/07/009",
        number="FV/2026/07/009",
        issue_date="03.07.2026", due_date="17.07.2026",
        seller_nip=BROKEN_NIP, buyer_nip=BUYER_NIP,
        rows=[
            ("Usługa A", 1, d("1000.00"), 23, d("1000.00")),
            ("Usługa B", 1, d("500.00"), 23, d("500.00")),
        ],
        # Net should be 1500.00 and gross 1845.00 — both are deliberately wrong.
        totals=(d("1600.00"), d("345.00"), d("1900.00")),
    ))

    for path in written:
        print("wrote", path)
    print(f"\nseller NIP {SELLER_NIP} (valid)  buyer NIP {BUYER_NIP} (valid)")
    print(f"broken NIP {BROKEN_NIP} (control digit deliberately wrong)")


if __name__ == "__main__":
    main()
