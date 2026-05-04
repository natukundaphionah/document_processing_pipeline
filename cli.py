# import typer
# from pathlib import Path
# import base64
# import time
# import logging
# import tempfile
# import sys
# import io

# from pdf2image import convert_from_bytes
# from PIL import Image

# from pypdf import PdfReader, PdfWriter

# from utils import (
#     get_client,
#     get_combined_markdown,
#     clean_markdown_pipeline,
#     get_pdf_files_in_directory
# )

# # -----------------------------
# # SETUP
# # -----------------------------
# sys.setrecursionlimit(10000)
# logging.getLogger("pypdf").setLevel(logging.ERROR)

# app = typer.Typer(help="OCR Pipeline with Image Cropping + Resume")

# MARKDOWN_DIR = Path("markdown")
# FAILED_LOG = Path("failed_files.txt")


# # -----------------------------
# # SAFE WRITE
# # -----------------------------
# def safe_write(file_path: Path, content: str):
#     try:
#         with open(file_path, "w", encoding="utf-8") as f:
#             f.write(content)
#     except OSError:
#         with open(file_path, "w", encoding="utf-8") as f:
#             chunk_size = 10000
#             for i in range(0, len(content), chunk_size):
#                 f.write(content[i:i + chunk_size])


# # -----------------------------
# # FAILED LOG
# # -----------------------------
# def log_failed(pdf_name: str, error: str):
#     with open(FAILED_LOG, "a", encoding="utf-8") as f:
#         f.write(f"{pdf_name} | {error}\n")


# # -----------------------------
# # DEDUP CHECK
# # -----------------------------
# def already_processed(pdf_path: Path) -> bool:
#     expected_md = MARKDOWN_DIR / pdf_path.name.replace(".pdf", ".md")
#     return expected_md.exists()


# # -----------------------------
# # PROGRESS
# # -----------------------------
# def show_progress(current, total, prefix="Progress"):
#     percent = (current / total) * 100 if total else 0
#     typer.echo(f"{prefix}: {current}/{total} pages ({percent:.1f}%)")


# # -----------------------------
# # IMAGE PROCESSING
# # -----------------------------
# def image_to_base64(image):
#     buffer = io.BytesIO()
#     image.save(buffer, format="PNG")
#     return base64.b64encode(buffer.getvalue()).decode("utf-8")


# # 🔥 NEW FIX: SPLIT DOUBLE PAGE SPREAD
# def split_two_pages(image):
#     width, height = image.size

#     # Slight adjustment for book fold
#     mid = int(width * 0.48)

#     left_page = image.crop((0, 0, mid, height))
#     right_page = image.crop((mid, 0, width, height))

#     return left_page, right_page


# # -----------------------------
# # OCR SINGLE IMAGE PAGE
# # -----------------------------
# def ocr_image(img, client):
#     img_b64 = image_to_base64(img)

#     response = client.ocr.process(
#         document={
#             "type": "image_url",
#             "image_url": f"data:image/png;base64,{img_b64}"
#         },
#         model="mistral-ocr-latest"
#     )

#     return get_combined_markdown(response)


# # -----------------------------
# # PROCESS PAGE (CORE FIX)
# # -----------------------------
# def process_single_page(pdf_bytes, client):

#     images = convert_from_bytes(pdf_bytes, dpi=150)
#     img = images[0]

#     # 🔥 SPLIT INTO TWO PAGES (IMPORTANT FIX)
#     left, right = split_two_pages(img)

#     results = []

#     for page in [left, right]:
#         results.append(ocr_image(page, client))

#     return "\n\n".join(results)


# # -----------------------------
# # FULL MODE
# # -----------------------------
# def process_full_pdf(pdf_path: Path, client, output_file: Path):

#     reader = PdfReader(pdf_path, strict=False)
#     total_pages = len(reader.pages)

#     typer.echo(f"📄 FULL MODE started ({total_pages} pages)")

#     results = []
#     temp_output = output_file.with_suffix(".tmp.md")

#     for i in range(total_pages):

#         writer = PdfWriter()
#         writer.add_page(reader.pages[i])

#         with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
#             writer.write(tmp)
#             tmp_path = Path(tmp.name)

#         try:
#             with open(tmp_path, "rb") as f:
#                 pdf_bytes = f.read()

#             markdown = process_single_page(pdf_bytes, client)

#             results.append(markdown)

#             safe_write(temp_output, "\n\n".join(results))
#             show_progress(i + 1, total_pages, prefix="FULL MODE")

#             time.sleep(0.3)

#         finally:
#             if tmp_path.exists():
#                 tmp_path.unlink()

#     return "\n\n".join(results)


# # -----------------------------
# # CHUNK MODE
# # -----------------------------
# def process_pdf_in_chunks(pdf_path: Path, client, output_dir: Path, chunk_size: int = 3):

#     reader = PdfReader(pdf_path, strict=False)
#     total_pages = len(reader.pages)

#     progress_file = output_dir / f"{pdf_path.stem}_progress.txt"
#     partial_file = output_dir / f"{pdf_path.stem}_partial.md"

#     start_page = 0

#     if progress_file.exists():
#         try:
#             start_page = int(progress_file.read_text().strip())
#             typer.echo(f"🔁 Resuming from page {start_page+1}")
#         except:
#             pass

#     results = []

#     if partial_file.exists():
#         try:
#             results.append(partial_file.read_text(encoding="utf-8"))
#         except:
#             pass

#     typer.echo(f"📦 CHUNK MODE started ({total_pages} pages)")

#     i = start_page

#     while i < total_pages:

#         writer = PdfWriter()

#         for p in range(i, min(i + chunk_size, total_pages)):
#             writer.add_page(reader.pages[p])

#         with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
#             writer.write(tmp)
#             tmp_path = Path(tmp.name)

#         try:
#             with open(tmp_path, "rb") as f:
#                 pdf_bytes = f.read()

#             images = convert_from_bytes(pdf_bytes, dpi=150)

#             page_results = []

#             for img in images:

#                 # 🔥 SPLIT FIX HERE TOO
#                 left, right = split_two_pages(img)

#                 for page in [left, right]:
#                     page_results.append(ocr_image(page, client))

#             markdown = "\n\n".join(page_results)

#             results.append(markdown)

#             end = min(i + chunk_size, total_pages)
#             safe_write(partial_file, "\n\n".join(results))
#             progress_file.write_text(str(end))

#             show_progress(end, total_pages, prefix="CHUNK MODE")

#             i = end
#             time.sleep(0.3)

#         except Exception:
#             typer.echo(f"⚠️ Skipping page {i+1}")
#             i += 1

#         finally:
#             if tmp_path.exists():
#                 tmp_path.unlink()

#     return "\n\n".join(results)


# # -----------------------------
# # MAIN PROCESSOR
# # -----------------------------
# def process_pdf(pdf_path: Path, output_dir: Path, client=None):

#     try:
#         if client is None:
#             client = get_client()

#         output_dir.mkdir(parents=True, exist_ok=True)
#         MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)

#         if already_processed(pdf_path):
#             typer.echo(f"⏭ Skipping {pdf_path.name}")
#             return

#         output_file = output_dir / pdf_path.name.replace(".pdf", ".md")

#         typer.echo(f"\n🚀 Processing → {pdf_path.name}")

#         try:
#             markdown = process_full_pdf(pdf_path, client, output_file)
#             typer.echo("✔ FULL MODE success")

#         except Exception as e:
#             typer.echo(f"Full mode failed: {e}")
#             typer.echo("Switching to chunk mode...")
#             markdown = process_pdf_in_chunks(pdf_path, client, output_dir)

#         try:
#             cleaned = clean_markdown_pipeline(markdown)
#         except:
#             cleaned = markdown

#         safe_write(output_file, cleaned)

#         typer.echo(f"🎉 Saved → {output_file}")

#     except Exception as e:
#         typer.echo(f" FAILED: {pdf_path.name}")
#         log_failed(pdf_path.name, str(e))


# # -----------------------------
# # CLI
# # -----------------------------
# @app.command()
# def process(
#     input_path: Path = typer.Option(..., help="PDF file or folder"),
#     output: Path = typer.Option(Path("markdown"), help="Output folder"),
# ):

#     client = get_client()

#     if input_path.is_file():
#         process_pdf(input_path, output, client)

#     elif input_path.is_dir():

#         pdfs = get_pdf_files_in_directory(str(input_path))

#         if not pdfs:
#             typer.echo("No PDFs found")
#             return

#         typer.echo(f"📚 Found {len(pdfs)} PDFs")

#         for idx, pdf in enumerate(pdfs, 1):
#             typer.echo(f"\n========== {idx}/{len(pdfs)} ==========")
#             process_pdf(Path(pdf), output, client)
#             time.sleep(0.5)

#         typer.echo("\n🎉 ALL DONE")

#     else:
#         typer.echo("Invalid path")


# if __name__ == "__main__":
#     app()
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

# -----------------------------
# CONFIG
# -----------------------------
sys.setrecursionlimit(10000)
logging.getLogger("pypdf").setLevel(logging.ERROR)

app = typer.Typer(help="Smart OCR PDF Processor (MB-based routing)")

RETRIES = 3
DELAY = 2
SKIPPED_LOG = "skipped.log"


# -----------------------------
# FILE SIZE (MB)
# -----------------------------
def get_file_size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


# -----------------------------
# STRATEGY DECISION (MB ONLY)
# -----------------------------
def choose_ocr_strategy(size_mb: float) -> str:
    if size_mb < 5:
        return "full"
    elif size_mb <= 25:
        return "chunk"
    else:
        return "page"


# -----------------------------
# LOGGING
# -----------------------------
def log_skipped(pdf_path: Path, reason: str):
    with open(SKIPPED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{pdf_path.name} - {reason}\n")


# -----------------------------
# OCR WITH RETRY
# -----------------------------
def ocr_with_retry(client, pdf_data_url, retries=RETRIES, delay=DELAY):
    for attempt in range(retries):
        try:
            return client.ocr.process(
                document=DocumentURLChunk(document_url=pdf_data_url),
                model="mistral-ocr-latest",
            )
        except SDKError as e:
            if "rate_limited" in str(e) or "timeout" in str(e):
                typer.echo(f"⚠️ Retry {attempt+1}/{retries} waiting {delay}s...")
                time.sleep(delay)
            else:
                raise

    raise RuntimeError("OCR failed after retries")


# -----------------------------
# PAGE OCR
# -----------------------------
def process_single_page(reader, i, client):
    writer = PdfWriter()
    writer.add_page(reader.pages[i])

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        writer.write(tmp)
        tmp_path = Path(tmp.name)

    try:
        with open(tmp_path, "rb") as f:
            page_bytes = f.read()

        page_b64 = base64.b64encode(page_bytes).decode("utf-8")
        page_data_url = f"data:application/pdf;base64,{page_b64}"

        response = ocr_with_retry(client, page_data_url)
        return get_combined_markdown(response)

    finally:
        tmp_path.unlink()


# -----------------------------
# FULL MODE
# -----------------------------
def process_full(reader, client):
    typer.echo("📄 FULL MODE")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.write(tmp)
        tmp_path = Path(tmp.name)

    try:
        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()

        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        pdf_data_url = f"data:application/pdf;base64,{pdf_b64}"

        response = ocr_with_retry(client, pdf_data_url)
        return get_combined_markdown(response)

    finally:
        tmp_path.unlink()


# -----------------------------
# CHUNK MODE (WITH PROGRESS)
# -----------------------------
def process_chunk(reader, client, pdf_path: Path, output_dir: Path, chunk_size=3):

    typer.echo("📦 CHUNK MODE")

    progress_file = output_dir / f"{pdf_path.stem}_progress.txt"
    partial_file = output_dir / f"{pdf_path.stem}_partial.md"

    start = 0
    if progress_file.exists():
        try:
            start = int(progress_file.read_text())
            typer.echo(f"🔁 Resuming chunk from {start}")
        except:
            start = 0

    results = []

    if partial_file.exists():
        try:
            results.append(partial_file.read_text(encoding="utf-8"))
        except:
            pass

    for i in range(start, len(reader.pages), chunk_size):

        writer = PdfWriter()

        for p in range(i, min(i + chunk_size, len(reader.pages))):
            writer.add_page(reader.pages[p])

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            writer.write(tmp)
            tmp_path = Path(tmp.name)

        try:
            with open(tmp_path, "rb") as f:
                pdf_bytes = f.read()

            pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
            pdf_data_url = f"data:application/pdf;base64,{pdf_b64}"

            response = ocr_with_retry(client, pdf_data_url)
            md = get_combined_markdown(response)

            results.append(md)

            # SAVE PROGRESS
            with open(partial_file, "w", encoding="utf-8") as f:
                f.write("\n\n".join(results))

            progress_file.write_text(str(i + chunk_size))

        finally:
            tmp_path.unlink()

    return "\n\n".join(results)


# -----------------------------
# PAGE MODE (WITH PROGRESS)
# -----------------------------
def process_pages(reader, client, pdf_path: Path, output_dir: Path):

    typer.echo("📑 PAGE-BY-PAGE MODE")

    progress_file = output_dir / f"{pdf_path.stem}_progress.txt"
    partial_file = output_dir / f"{pdf_path.stem}_partial.md"

    start = 0
    if progress_file.exists():
        try:
            start = int(progress_file.read_text())
            typer.echo(f"🔁 Resuming from page {start+1}")
        except:
            start = 0

    results = []

    if partial_file.exists():
        try:
            results.append(partial_file.read_text(encoding="utf-8"))
        except:
            pass

    for i in range(start, len(reader.pages)):

        typer.echo(f"Processing page {i+1}/{len(reader.pages)}")

        try:
            md = process_single_page(reader, i, client)
            results.append(f"\n\n## Page {i+1}\n\n{md}")

            # SAVE PROGRESS LIVE
            with open(partial_file, "w", encoding="utf-8") as f:
                f.write("\n\n".join(results))

            progress_file.write_text(str(i + 1))

        except Exception as e:
            log_skipped(Path("pdf"), f"Page {i+1}: {e}")

        time.sleep(0.3)

    return "\n\n".join(results)


# -----------------------------
# MAIN PROCESSOR
# -----------------------------
def process_pdf(pdf_path: Path, output_dir: Path, client=None):

    if client is None:
        client = get_client()

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / pdf_path.name.replace(".pdf", ".md")

    if output_file.exists():
        typer.echo(f"⏭ Skipping {pdf_path.name}")
        return

    typer.echo(f"\n🚀 Processing → {pdf_path.name}")

    size_mb = get_file_size_mb(pdf_path)
    reader = PdfReader(pdf_path, strict=False)

    typer.echo(f"📊 Size: {size_mb:.2f} MB | Pages: {len(reader.pages)}")

    mode = choose_ocr_strategy(size_mb)
    typer.echo(f"🧠 Mode selected: {mode}")

    try:
        if mode == "full":
            markdown = process_full(reader, client)

        elif mode == "chunk":
            markdown = process_chunk(reader, client, pdf_path, output_dir)

        else:
            markdown = process_pages(reader, client, pdf_path, output_dir)

        cleaned = clean_markdown_pipeline(markdown)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(cleaned)

        typer.echo(f"✅ Saved → {output_file}")

    except Exception as e:
        typer.echo(f"❌ Failed {pdf_path.name}: {e}")
        log_skipped(pdf_path, str(e))


# -----------------------------
# CLI
# -----------------------------
@app.command()
def process(
    input_path: Path = typer.Option(...),
    output: Path = typer.Option(Path("markdown")),
):

    client = get_client()

    if input_path.is_file():
        process_pdf(input_path, output, client)

    elif input_path.is_dir():
        pdfs = get_pdf_files_in_directory(str(input_path))

        for pdf in pdfs:
            process_pdf(Path(pdf), output, client)
            time.sleep(0.5)

    else:
        typer.echo("Invalid path")


if __name__ == "__main__":
    app()