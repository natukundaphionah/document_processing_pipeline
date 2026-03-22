import typer
from pathlib import Path
import base64
import time
import logging
import tempfile
import sys

from mistralai import DocumentURLChunk
from mistralai.models import SDKError
from pypdf import PdfReader, PdfWriter

from utils import (
    get_client,
    get_combined_markdown,
    clean_markdown_pipeline,
    get_pdf_files_in_directory
)

# Prevent recursion errors in large PDFs
sys.setrecursionlimit(10000)

# Suppress pypdf warnings
logging.getLogger("pypdf").setLevel(logging.ERROR)

app = typer.Typer(
    help="Mistral OCR PDF Processor CLI – Converts PDFs to cleaned Markdown files."
)

# Constants
RETRIES = 3
DELAY = 2
SKIPPED_LOG = "skipped.log"
CHUNK_SIZE = 80  # pages per chunk when splitting


def log_skipped(pdf_path: Path, reason: str):
    """Log skipped PDFs to a file."""
    with open(SKIPPED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{pdf_path.name} - {reason}\n")


def ocr_with_retry(client, pdf_data_url, retries=RETRIES, delay=DELAY):
    """Call Mistral OCR with retry on transient errors."""
    for attempt in range(retries):
        try:
            return client.ocr.process(
                document=DocumentURLChunk(document_url=pdf_data_url),
                model="mistral-ocr-latest",
            )
        except SDKError as e:
            if "rate_limited" in str(e) or "timeout" in str(e):
                typer.echo(
                    f"⚠️ Retry {attempt+1}/{retries} due to temporary error, waiting {delay}s..."
                )
                time.sleep(delay)
            else:
                raise

    raise RuntimeError("Exceeded retries due to repeated errors.")


def process_pdf(pdf_path: Path, output_dir: Path, client=None):
    """Process a single PDF. If too large, split it into chunks."""

    if client is None:
        client = get_client()

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{pdf_path.stem}.md"

    # Skip if already processed
    if output_file.exists():
        typer.echo(f"Skipping '{pdf_path.name}' – already processed.")
        return

    typer.echo(f"\nProcessing → {pdf_path}")

    # Encode full PDF
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    pdf_data_url = f"data:application/pdf;base64,{pdf_b64}"

    try:
        # Try normal OCR first
        ocr_response = ocr_with_retry(client, pdf_data_url)
        markdown = get_combined_markdown(ocr_response)

    except SDKError as e:

        # Only split if request size exceeded
        if "Request size limit exceeded" not in str(e):
            reason = str(e)
            typer.echo(f"Skipping '{pdf_path.name}' – {reason}")
            log_skipped(pdf_path, reason)
            return

        typer.echo("PDF too large — splitting into chunks...")

        reader = PdfReader(pdf_path, strict=False)
        total_pages = len(reader.pages)
        markdown_parts = []

        for start in range(0, total_pages, CHUNK_SIZE):

            end = min(start + CHUNK_SIZE, total_pages)

            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                writer.write(tmp)
                tmp_path = Path(tmp.name)

            with open(tmp_path, "rb") as f:
                chunk_bytes = f.read()

            chunk_b64 = base64.b64encode(chunk_bytes).decode("utf-8")
            chunk_data_url = f"data:application/pdf;base64,{chunk_b64}"

            typer.echo(f"Processing pages {start+1}-{end}")

            try:
                chunk_response = ocr_with_retry(client, chunk_data_url)
                markdown_parts.append(get_combined_markdown(chunk_response))
            except Exception as chunk_error:
                typer.echo(f"Failed chunk {start+1}-{end}: {chunk_error}")

            tmp_path.unlink()

        markdown = "\n\n".join(markdown_parts)

    # Clean OCR text
    cleaned = clean_markdown_pipeline(markdown)

    # Save markdown
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(cleaned)

    typer.echo(f"Saved → {output_file}")


@app.command()
def process(
    input_path: Path = typer.Option(..., help="Path to a PDF file or folder"),
    output: Path = typer.Option(
        Path("markdown"), help="Directory to save the cleaned markdown files"
    ),
):
    """Process PDFs from a folder or single file."""

    client = get_client()

    if input_path.is_file():

        process_pdf(input_path, output, client=client)

    elif input_path.is_dir():

        pdf_files = get_pdf_files_in_directory(str(input_path))

        if not pdf_files:
            typer.echo(f"No PDF files found in {input_path}")
            return

        for pdf in pdf_files:
            process_pdf(Path(pdf), output, client=client)
            time.sleep(0.5)

    else:
        typer.echo(f"Path '{input_path}' does not exist.")


if __name__ == "__main__":
    app()