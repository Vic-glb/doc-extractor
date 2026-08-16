"""
Data model.

The central rule of this tool is expressed here: an extracted field is never a
bare value. It is a `Field`, which always carries how sure the extractor is and
what text in the document it came from. A field that was not found holds `None`
and says so — it is never filled with a plausible-looking value.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class Confidence(str, Enum):
    """How much the extractor trusts one field."""

    #: A label was matched and the value parsed cleanly.
    FOUND = "found"
    #: Something was read, but the evidence is weak — an unusual label, an
    #: unexpected format, or a value that failed a consistency check. A human
    #: should look at it.
    UNCERTAIN = "uncertain"
    #: Nothing usable was found. The value is None.
    MISSING = "missing"


@dataclass(frozen=True)
class Field(Generic[T]):
    """One extracted value, with its provenance.

    Attributes:
        value: The parsed value, or None when nothing was found.
        confidence: See `Confidence`.
        evidence: The snippet of document text the value was read from, so a
            human can check the extraction without opening the PDF.
        page: 1-based page the value was found on.
        note: Why the field is uncertain or missing, in plain language.
    """

    value: T | None = None
    confidence: Confidence = Confidence.MISSING
    evidence: str = ""
    page: int | None = None
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.confidence is Confidence.FOUND

    @property
    def needs_review(self) -> bool:
        return self.confidence is not Confidence.FOUND

    @classmethod
    def missing(cls, note: str = "") -> "Field[T]":
        return cls(value=None, confidence=Confidence.MISSING, note=note)

    @classmethod
    def found(cls, value: T, evidence: str = "", page: int | None = None) -> "Field[T]":
        return cls(value=value, confidence=Confidence.FOUND, evidence=evidence, page=page)

    @classmethod
    def uncertain(cls, value: T | None, note: str, evidence: str = "",
                  page: int | None = None) -> "Field[T]":
        return cls(value=value, confidence=Confidence.UNCERTAIN, evidence=evidence,
                   page=page, note=note)

    def as_json(self) -> dict[str, Any]:
        """Render for the JSON output, keeping value and confidence together."""
        return {
            "value": _plain(self.value),
            "confidence": self.confidence.value,
            "evidence": self.evidence,
            "page": self.page,
            "note": self.note,
        }


@dataclass
class LineItem:
    """One row of the invoice table."""

    description: str = ""
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    net_amount: Decimal | None = None
    vat_rate: Decimal | None = None
    page: int = 1
    #: The raw table row, kept so a human can see what was read.
    raw: list[str] = dataclass_field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "quantity": _plain(self.quantity),
            "unit_price": _plain(self.unit_price),
            "net_amount": _plain(self.net_amount),
            "vat_rate": _plain(self.vat_rate),
            "page": self.page,
        }


class Level(str, Enum):
    """Severity of a consistency finding."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Finding:
    """The result of one consistency check."""

    check: str
    level: Level
    message: str
    #: Populated when the check compared two numbers.
    expected: Decimal | None = None
    actual: Decimal | None = None

    @property
    def difference(self) -> Decimal | None:
        if self.expected is None or self.actual is None:
            return None
        return self.actual - self.expected

    def as_json(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "level": self.level.value,
            "message": self.message,
            "expected": _plain(self.expected),
            "actual": _plain(self.actual),
            "difference": _plain(self.difference),
        }


@dataclass
class Party:
    """A seller or a buyer."""

    name: Field[str] = dataclass_field(default_factory=Field)
    tax_id: Field[str] = dataclass_field(default_factory=Field)
    address: Field[str] = dataclass_field(default_factory=Field)

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name.as_json(),
            "tax_id": self.tax_id.as_json(),
            "address": self.address.as_json(),
        }


@dataclass
class Invoice:
    """Everything extracted from one document."""

    source: str = ""
    pages: int = 0

    number: Field[str] = dataclass_field(default_factory=Field)
    issue_date: Field[date] = dataclass_field(default_factory=Field)
    due_date: Field[date] = dataclass_field(default_factory=Field)
    currency: Field[str] = dataclass_field(default_factory=Field)

    seller: Party = dataclass_field(default_factory=Party)
    buyer: Party = dataclass_field(default_factory=Party)

    net_total: Field[Decimal] = dataclass_field(default_factory=Field)
    vat_total: Field[Decimal] = dataclass_field(default_factory=Field)
    gross_total: Field[Decimal] = dataclass_field(default_factory=Field)

    lines: list[LineItem] = dataclass_field(default_factory=list)
    findings: list[Finding] = dataclass_field(default_factory=list)

    def all_fields(self) -> dict[str, Field]:
        """Top-level fields, keyed by the name used in the outputs."""
        return {
            "number": self.number,
            "issue_date": self.issue_date,
            "due_date": self.due_date,
            "currency": self.currency,
            "seller_name": self.seller.name,
            "seller_tax_id": self.seller.tax_id,
            "buyer_name": self.buyer.name,
            "buyer_tax_id": self.buyer.tax_id,
            "net_total": self.net_total,
            "vat_total": self.vat_total,
            "gross_total": self.gross_total,
        }

    def fields_needing_review(self) -> dict[str, Field]:
        return {name: f for name, f in self.all_fields().items() if f.needs_review}

    def has_errors(self) -> bool:
        return any(f.level is Level.ERROR for f in self.findings)

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "pages": self.pages,
            "number": self.number.as_json(),
            "issue_date": self.issue_date.as_json(),
            "due_date": self.due_date.as_json(),
            "currency": self.currency.as_json(),
            "seller": self.seller.as_json(),
            "buyer": self.buyer.as_json(),
            "totals": {
                "net": self.net_total.as_json(),
                "vat": self.vat_total.as_json(),
                "gross": self.gross_total.as_json(),
            },
            "lines": [line.as_json() for line in self.lines],
            "checks": [finding.as_json() for finding in self.findings],
        }


def _plain(value: Any) -> Any:
    """Convert Decimal and date to JSON-friendly values without losing precision."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
