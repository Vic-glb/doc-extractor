"""Shared fixtures."""
from pathlib import Path

import pytest

SAMPLES = Path(__file__).parent.parent / "samples"


@pytest.fixture(scope="session")
def samples() -> Path:
    if not (SAMPLES / "invoice_pl_simple.pdf").exists():
        pytest.skip("run `python samples/make_invoices.py` first")
    return SAMPLES


@pytest.fixture(scope="session")
def extracted(samples):
    """Every sample invoice, extracted once and shared by the tests."""
    from doc_extractor.cli import process

    return {
        path.stem: process(path)
        for path in sorted(samples.glob("invoice_*.pdf"))
    }


@pytest.fixture
def scanned_pdf(tmp_path) -> Path:
    """A PDF with a drawing but no text layer, standing in for a scan."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "scan.pdf"
    sheet = canvas.Canvas(str(path), pagesize=A4)
    sheet.rect(60, 600, 400, 120, fill=0)
    sheet.line(60, 560, 460, 560)
    sheet.showPage()
    sheet.save()
    return path
