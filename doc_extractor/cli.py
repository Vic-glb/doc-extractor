"""
Command line entry point.

    python -m doc_extractor extract samples/*.pdf --json out.json

One document that cannot be read does not stop a batch: the failure is printed
and the run continues, so a folder of invoices with one scan in it still yields
the other results.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .extract import extract_invoice
from .image import export_png
from .lines import extract_lines
from .model import Invoice
from .output import write_fields_csv, write_json, write_lines_csv
from .report import render_invoice, render_summary
from .sources import EmptyTextLayer, PdfTextSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc-extractor",
        description="Extract structured data from text-based invoice PDFs, and check that "
                    "the numbers add up.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("extract", help="extract one or more invoices")
    run.add_argument("inputs", type=Path, nargs="+", help="invoice PDF files")
    run.add_argument("--json", type=Path, help="write the full result as JSON")
    run.add_argument("--fields-csv", type=Path, help="write one row per extracted field")
    run.add_argument("--lines-csv", type=Path, help="write one row per invoice line")
    run.add_argument("--export-png", type=Path, help="save the console output as a PNG")
    run.add_argument("--width", type=int,
                     help="force the output width in characters. Set automatically to 110 "
                          "when exporting an image, so the image does not depend on the "
                          "terminal it was produced in")
    run.add_argument("--no-lines", action="store_true", help="hide the line-item tables")
    run.add_argument("--summary-only", action="store_true",
                     help="print one row per document instead of the full detail")
    run.add_argument("--fail-on-error", action="store_true",
                     help="exit with code 2 if any document does not add up")

    show = sub.add_parser(
        "demo",
        help="run over the bundled sample invoices and print a readable overview",
    )
    show.add_argument("--samples", type=Path, default=Path("samples"),
                      help="folder holding the sample invoices (default: samples)")
    show.add_argument("--export-png", type=Path, help="save the output as a PNG")
    show.add_argument("--width", type=int, default=118, help="output width (default: 118)")
    return parser


def process(path: Path) -> Invoice:
    """Read and check one document.

    Raises:
        EmptyTextLayer: If the PDF has no text layer (typically a scan).
        ValueError: If the file type is not supported.
    """
    source = PdfTextSource()
    if not source.supports(path):
        raise ValueError(f"{path.name}: only PDF files are supported")
    pages = source.read(path)
    invoice = extract_invoice(pages, path.name)
    invoice.lines, skipped = extract_lines(pages)

    from .validate import run_checks
    invoice.findings = run_checks(invoice, skipped)
    return invoice


def run_demo(args) -> int:
    """Extract the bundled samples and print the overview tables."""
    from .demo import render_arithmetic, render_field_matrix, render_notes, sample_paths

    console = Console(record=bool(args.export_png), width=args.width)

    paths = sample_paths(args.samples)
    if not paths:
        console.print(
            f"[red]No sample invoices found in {args.samples}.[/red]\n"
            "Generate them first: python samples/make_invoices.py"
        )
        return 1

    invoices: list[Invoice] = []
    for path in paths:
        try:
            invoices.append(process(path))
        except (EmptyTextLayer, OSError, ValueError) as exc:
            console.print(f"[red]Skipped {path.name}:[/red] {exc}")

    if not invoices:
        console.print("[red]Nothing could be extracted.[/red]")
        return 1

    console.print()
    render_field_matrix(invoices, console)
    console.print()
    render_arithmetic(invoices, console)
    console.print()
    render_notes(invoices, console)

    if args.export_png:
        try:
            export_png(console, args.export_png)
            console.print(f"\n[bold #3FB950]Image:[/bold #3FB950] {args.export_png}")
        except (OSError, ValueError, ImportError) as exc:
            console.print(f"[#D29922]Could not write the PNG:[/#D29922] {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        return run_demo(args)

    exporting = bool(args.export_png)
    width = args.width or (110 if exporting else None)
    console = Console(record=exporting, width=width)

    invoices: list[Invoice] = []
    failures = 0

    for path in args.inputs:
        if not path.exists():
            console.print(f"[red]File not found:[/red] {path}")
            failures += 1
            continue
        try:
            invoices.append(process(path))
        except EmptyTextLayer as exc:
            # The single most likely failure in real use, so it gets its own
            # message rather than a generic one.
            console.print(f"[red]Skipped {path.name}:[/red] {exc}")
            failures += 1
        except (OSError, ValueError) as exc:
            console.print(f"[red]Skipped {path.name}:[/red] {exc}")
            failures += 1

    if not invoices:
        console.print("[red]Nothing could be extracted.[/red]")
        return 1

    if args.summary_only or len(invoices) > 1:
        render_summary(invoices, console)
        console.print()
    if not args.summary_only:
        for invoice in invoices:
            render_invoice(invoice, console, show_lines=not args.no_lines)
            console.print()

    try:
        if args.json:
            write_json(invoices, args.json)
            console.print(f"[bold #3FB950]JSON:[/bold #3FB950]       {args.json}")
        if args.fields_csv:
            write_fields_csv(invoices, args.fields_csv)
            console.print(f"[bold #3FB950]Fields CSV:[/bold #3FB950] {args.fields_csv}")
        if args.lines_csv:
            write_lines_csv(invoices, args.lines_csv)
            console.print(f"[bold #3FB950]Lines CSV:[/bold #3FB950]  {args.lines_csv}")
    except OSError as exc:
        console.print(f"[red]Cannot write the output:[/red] {exc}")
        return 1

    if args.export_png:
        try:
            export_png(console, args.export_png)
            console.print(f"[bold #3FB950]Image:[/bold #3FB950]      {args.export_png}")
        except (OSError, ValueError, ImportError) as exc:
            console.print(f"[#D29922]Could not write the PNG:[/#D29922] {exc}")

    if failures:
        console.print(f"\n[#D29922]{failures} document(s) could not be read.[/#D29922]")
    if args.fail_on_error and any(invoice.has_errors() for invoice in invoices):
        console.print("[#5FA8FF]Some documents do not add up — see the checks above.[/#5FA8FF]")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
