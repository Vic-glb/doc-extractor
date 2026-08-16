"""
Where the text comes from.

Extraction never opens a PDF itself. It works on `Page` objects handed to it by a
`TextSource`. Today there is one implementation, `PdfTextSource`, which reads the
text layer of a digital PDF. An OCR-backed source would implement the same three
members and everything downstream — labels, line items, arithmetic checks, output
— would keep working untouched.

That seam is the reason `Word` carries coordinates even though the current
implementation could get away with plain strings: an OCR engine returns boxes,
and the interface has to be able to express them from the start.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Word:
    """One word and where it sits on the page, in PDF points from the top left."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass
class Page:
    """One page of a document, as text plus positioned words."""

    number: int
    text: str
    words: list[Word] = field(default_factory=list)
    #: Tables as rows of cells, when the source can detect them. An OCR source
    #: may return an empty list here; line extraction falls back to text layout.
    tables: list[list[list[str]]] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [line.rstrip() for line in self.text.splitlines()]


@runtime_checkable
class TextSource(Protocol):
    """Anything that can turn a file into pages of text."""

    #: Human-readable name, used in reports and error messages.
    name: str

    def supports(self, path: Path) -> bool:
        """True when this source can handle the file."""

    def read(self, path: Path) -> list[Page]:
        """Return one `Page` per page of the document."""


class EmptyTextLayer(Exception):
    """Raised when a PDF has no extractable text.

    Almost always means the file is a scan. The message says so explicitly rather
    than letting the tool return an empty invoice, which would look like a
    document that simply had no fields.
    """


class PdfTextSource:
    """Reads the text layer of a digital PDF using pdfplumber."""

    name = "PDF text layer"

    #: Below this many characters across the whole document, we treat the text
    #: layer as absent. A scan run through a naive converter can carry a handful
    #: of stray characters, which is not enough to extract anything from.
    MIN_CHARACTERS = 40

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def read(self, path: Path) -> list[Page]:
        """Read every page.

        Raises:
            EmptyTextLayer: If the document carries no usable text layer.
        """
        import pdfplumber

        pages: list[Page] = []
        with pdfplumber.open(path) as document:
            for index, raw_page in enumerate(document.pages, start=1):
                text = raw_page.extract_text() or ""
                words = [
                    Word(
                        text=word["text"],
                        x0=float(word["x0"]),
                        top=float(word["top"]),
                        x1=float(word["x1"]),
                        bottom=float(word["bottom"]),
                    )
                    for word in raw_page.extract_words()
                ]
                tables = raw_page.extract_tables() or []
                cleaned = [
                    [[cell if cell is not None else "" for cell in row] for row in table]
                    for table in tables
                ]
                pages.append(Page(number=index, text=text, words=words, tables=cleaned))

        total = sum(len(page.text.strip()) for page in pages)
        if total < self.MIN_CHARACTERS:
            raise EmptyTextLayer(
                f"{path.name} has no text layer ({total} characters found). "
                "This looks like a scan; scanned documents are not supported."
            )
        return pages
