"""Tests for the JSON/CSV outputs, the PNG export and the command line."""
import csv
import json

from PIL import Image

from doc_extractor.cli import main
from doc_extractor.output import write_fields_csv, write_json, write_lines_csv


# --------------------------------------------------------------------- outputs


def test_json_keeps_the_confidence_next_to_every_value(extracted, tmp_path):
    out = tmp_path / "out.json"

    write_json([extracted["invoice_pl_simple"]], out)
    payload = json.loads(out.read_text(encoding="utf-8"))

    number = payload["invoices"][0]["number"]
    assert number["value"] == "FV/2026/03/017"
    assert number["confidence"] == "found"
    assert "evidence" in number and "page" in number


def test_json_reports_a_missing_field_as_null_and_missing(tmp_path):
    from doc_extractor.extract import extract_invoice
    from doc_extractor.sources import Page

    invoice = extract_invoice([Page(number=1, text="nothing here")], "x.pdf")
    out = tmp_path / "out.json"

    write_json([invoice], out)
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["invoices"][0]["number"]["value"] is None
    assert payload["invoices"][0]["number"]["confidence"] == "missing"


def test_json_keeps_amounts_exact_by_writing_them_as_strings(extracted, tmp_path):
    # Writing 8265.60 as a JSON float would introduce a binary rounding error in
    # whatever reads it back; money stays a string.
    out = tmp_path / "out.json"

    write_json([extracted["invoice_pl_simple"]], out)
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["invoices"][0]["totals"]["gross"]["value"] == "8265.60"


def test_json_summary_counts_documents_with_errors(extracted, tmp_path):
    out = tmp_path / "out.json"

    write_json([extracted["invoice_pl_simple"], extracted["invoice_pl_inconsistent"]], out)
    summary = json.loads(out.read_text(encoding="utf-8"))["summary"]

    assert summary["documents"] == 2
    assert summary["with_errors"] == 1


def test_fields_csv_has_one_row_per_field(extracted, tmp_path):
    out = tmp_path / "fields.csv"

    write_fields_csv([extracted["invoice_pl_simple"]], out)
    rows = list(csv.DictReader(out.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))

    assert len(rows) == len(extracted["invoice_pl_simple"].all_fields())
    assert {"field", "value", "confidence"} <= set(rows[0])


def test_lines_csv_has_one_row_per_line_item(extracted, tmp_path):
    out = tmp_path / "lines.csv"

    write_lines_csv([extracted["invoice_pl_multipage"]], out)
    rows = list(csv.DictReader(out.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))

    assert len(rows) == 18
    assert rows[0]["invoice_number"] == "FV/2026/05/044"


def test_csv_files_carry_a_bom_for_excel(extracted, tmp_path):
    out = tmp_path / "fields.csv"
    write_fields_csv([extracted["invoice_pl_simple"]], out)

    assert out.read_bytes().startswith(b"\xef\xbb\xbf")


# ------------------------------------------------------------------------- cli


SIMPLE = "samples/invoice_pl_simple.pdf"
BROKEN = "samples/invoice_pl_inconsistent.pdf"


def test_successful_run_exits_zero_and_writes_the_requested_files(tmp_path):
    code = main(["extract", SIMPLE,
                 "--json", str(tmp_path / "o.json"),
                 "--fields-csv", str(tmp_path / "f.csv"),
                 "--lines-csv", str(tmp_path / "l.csv")])

    assert code == 0
    assert (tmp_path / "o.json").exists()
    assert (tmp_path / "f.csv").exists()
    assert (tmp_path / "l.csv").exists()


def test_missing_file_is_reported_and_the_run_returns_one(tmp_path, capsys):
    code = main(["extract", str(tmp_path / "nope.pdf")])

    assert code == 1
    assert "File not found" in capsys.readouterr().out


def test_a_scan_is_skipped_with_an_explanation_but_the_batch_continues(scanned_pdf, capsys):
    code = main(["extract", str(scanned_pdf), SIMPLE, "--summary-only"])
    output = capsys.readouterr().out

    assert code == 0, "one unreadable file must not lose the readable ones"
    assert "scan" in output
    assert "1 document(s) could not be read" in output


def test_fail_on_error_exits_two_for_an_invoice_that_does_not_add_up(tmp_path):
    assert main(["extract", BROKEN, "--fail-on-error", "--summary-only"]) == 2


def test_fail_on_error_exits_zero_for_a_consistent_invoice():
    assert main(["extract", SIMPLE, "--fail-on-error", "--summary-only"]) == 0


def test_several_documents_are_summarised_together(capsys):
    # The width is pinned so the assertion does not depend on the terminal the
    # tests happen to run in — a narrow one folds the file names across lines.
    main(["extract", SIMPLE, BROKEN, "--summary-only", "--width", "120"])
    output = capsys.readouterr().out

    assert "Summary" in output
    assert "invoice_pl_simple.pdf" in output
    assert "invoice_pl_inconsistent.pdf" in output


def test_width_can_be_forced_for_redirected_output(capsys):
    main(["extract", SIMPLE, "--summary-only", "--width", "100"])
    output = capsys.readouterr().out

    longest = max(len(line) for line in output.splitlines() if line.strip())
    assert longest <= 100


def test_png_export_produces_a_real_image(tmp_path):
    png = tmp_path / "run.png"

    code = main(["extract", SIMPLE, "--export-png", str(png)])

    assert code == 0
    with Image.open(png) as image:
        assert image.format == "PNG"
        assert image.height > 300


# ------------------------------------------------------------------------ demo


def test_demo_covers_every_sample_and_shows_both_tables(capsys):
    code = main(["demo"])
    output = capsys.readouterr().out

    assert code == 0
    assert "Every field, and how sure the extractor is" in output
    assert "Does the invoice agree with itself?" in output
    # The three statuses must all be visible: that is the point of the table.
    for status in ("found", "check this"):
        assert status in output


def test_demo_shows_the_arithmetic_gap_of_the_broken_invoice(capsys):
    main(["demo"])
    output = capsys.readouterr().out

    assert "does not add up" in output
    assert "100.00" in output, "the gap between computed and stated should be shown"


def test_demo_explains_every_flagged_field(capsys):
    main(["demo"])
    output = capsys.readouterr().out

    assert "What was flagged, and why" in output
    assert "control digit" in output


def test_demo_reports_a_missing_samples_folder(tmp_path, capsys):
    code = main(["demo", "--samples", str(tmp_path)])

    assert code == 1
    assert "No sample invoices found" in capsys.readouterr().out


def test_demo_can_export_an_image(tmp_path):
    png = tmp_path / "demo.png"
    assert main(["demo", "--export-png", str(png)]) == 0

    with Image.open(png) as image:
        assert image.height > 400
