"""Bounded, offline PDF extraction in a disposable process.

Only Tesseract (ara+eng), PDFium and pdfplumber are used. Nothing is downloaded
at runtime. Worker isolation also avoids PDFium's thread-safety restrictions.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 20
MAX_PIXELS = 12_000_000
MAX_OUTPUT = 8 * 1024 * 1024
DOCUMENT_TIMEOUT = 45
NUMBER_CONFIDENCE = 85
_SLOTS = threading.BoundedSemaphore(2)


def extract_pdf(raw: bytes, progress=None) -> dict:
    if len(raw) > MAX_BYTES:
        raise ValueError("PDF exceeds the local OCR limit of 25 MB; split the document.")
    if not _SLOTS.acquire(blocking=False):
        raise ValueError("Local PDF workers are busy. Please retry shortly.")
    try:
        with tempfile.TemporaryDirectory(prefix="awi-pdf-") as directory:
            root = Path(directory)
            (root / "input.pdf").write_bytes(raw)
            process = subprocess.Popen(
                [sys.executable, "-m", "backend.core.local_pdf_ocr", directory],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                start_new_session=True,
            )
            deadline = time.monotonic() + DOCUMENT_TIMEOUT
            seen = 0
            try:
                while True:
                    finished = process.poll() is not None
                    events = root / "progress"
                    if events.exists():
                        lines = [line for line in events.read_text().splitlines(keepends=True) if line.endswith("\n")]
                        for line in lines[seen:]:
                            if progress:
                                progress(json.loads(line))
                        seen = len(lines)
                    if finished:
                        break
                    if time.monotonic() >= deadline:
                        raise ValueError("Local PDF OCR timed out after 45 seconds; split the document.")
                    time.sleep(0.1)
                output = root / "result"
                if not output.exists() or output.stat().st_size > MAX_OUTPUT:
                    raise ValueError("Local PDF worker stopped or exceeded its resource limit. Split the PDF.")
                result = json.loads(output.read_text())
                if result.get("error"):
                    raise ValueError(result["error"])
                return result
            finally:
                # Kill descendants too: cancelling a thread alone cannot stop OCR.
                import signal
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
    finally:
        _SLOTS.release()


def _ocr_page(page, root: Path) -> dict:
    width, height = page.get_size()
    scale = 200 / 72
    if not all(math.isfinite(v) and 0 < v <= 14400 for v in (width, height)):
        raise ValueError("PDF page dimensions exceed safe local rasterization limits.")
    if math.ceil(width * scale) * math.ceil(height * scale) > MAX_PIXELS:
        raise ValueError("PDF page exceeds the 12 megapixel OCR limit; resize the source page.")
    bitmap = page.render(scale=scale)
    try:
        image = bitmap.to_pil()
        try:
            image.save(root / "page.png")
        finally:
            image.close()
    finally:
        bitmap.close()
    try:
        subprocess.run(
            ["tesseract", str(root / "page.png"), str(root / "ocr"),
             "-l", "ara+eng", "--psm", "3", "tsv"],
            check=True, timeout=15, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("OCR page exceeded its 15-second limit; split or simplify the PDF.") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError("Local Tesseract OCR failed. Verify Arabic and English language data.") from exc
    tsv = root / "ocr.tsv"
    if tsv.stat().st_size > MAX_OUTPUT:
        raise ValueError("OCR output exceeded its resource limit.")
    return _parse_tsv(tsv.read_text())


def _parse_tsv(text: str) -> dict:
    """Keep token confidence internally; return only governed text and safe counts."""
    lines: dict[tuple, list[str]] = {}
    scores = []
    low_numbers = 0
    for row in csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        token = (row.get("text") or "").strip()
        if row.get("level") != "5" or not token:
            continue
        score = float(row["conf"])
        if not math.isfinite(score) or not 0 <= score <= 100:
            score = 0.0
        scores.append(score)
        if any(char.isdigit() for char in token) and score < NUMBER_CONFIDENCE:
            low_numbers += 1
        key = tuple(row.get(name) for name in ("block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(token)
    return {
        "text": "\n".join(" ".join(words) for words in lines.values()),
        "confidence": round(sum(scores) / len(scores), 2) if scores else 0.0,
        "low_confidence_numbers": low_numbers,
    }


def _worker(root: Path) -> dict:
    import pdfplumber
    import pypdfium2 as pdfium

    def event(**values):
        with (root / "progress").open("a") as stream:
            stream.write(json.dumps(values) + "\n")

    event(stage="parsing")
    tables, passages, pages, warnings = [], [], [], []
    with pdfium.PdfDocument(str(root / "input.pdf")) as raster:
        if len(raster) > MAX_PAGES:
            raise ValueError("PDF has more than 20 pages; split it before local extraction.")
        with pdfplumber.open(root / "input.pdf") as pdf:
            for number, page in enumerate(pdf.pages, 1):
                native = (page.extract_text() or "").strip()
                # OCR images even on pages that have a searchable header.
                # Small image footnotes can contain material figures too. A
                # searchable heading or logo is not proof a page is complete.
                scan = not native or bool(page.images)
                method = ("native+ocr" if native else "ocr") if scan else "native"
                event(stage="extracting", page=number, total_pages=len(raster), method=method)
                info = {"page": number, "method": method, "confidence": None,
                        "low_confidence_numbers": 0}
                text = native
                if scan:
                    if not shutil.which("tesseract"):
                        raise ValueError("Local OCR unavailable: install Tesseract with ara and eng language data.")
                    check = subprocess.run(
                        ["tesseract", "--list-langs"], capture_output=True, text=True,
                        check=True, timeout=5,
                    )
                    if not {"ara", "eng"} <= set(check.stdout.split()):
                        raise ValueError("Local OCR requires both Arabic (ara) and English (eng) Tesseract language data.")
                    raster_page = raster[number - 1]
                    try:
                        ocr = _ocr_page(raster_page, root)
                    finally:
                        raster_page.close()
                    info.update({key: ocr[key] for key in ("confidence", "low_confidence_numbers")})
                    if ocr["text"] and ocr["text"] != native:
                        text = (native + "\n" + ocr["text"]).strip()
                    if not ocr["text"]:
                        raise ValueError(f"OCR found no readable text on page {number}. Supply a clearer scan.")
                    if ocr["low_confidence_numbers"] or ocr["confidence"] < 70:
                        warnings.append(f"Page {number}: low-confidence OCR; numbers require clarification and a verified source.")
                pages.append(info)
                if text:
                    passages.append({"PDF page": number, "PDF text": text,
                                     "PDF extraction method": method,
                                     "OCR confidence": info["confidence"]})
                extracted = page.extract_tables() or []
                if not extracted and native:
                    extracted = page.extract_tables(table_settings={
                        "vertical_strategy": "text", "horizontal_strategy": "text",
                        "text_x_tolerance": 3, "text_y_tolerance": 3,
                    }) or []
                for table in extracted:
                    if len(table) < 2 or not table[0]:
                        continue
                    headers = [str(v).strip() if v is not None and str(v).strip()
                               else f"Column {i + 1}" for i, v in enumerate(table[0])]
                    rows = [row for row in table[1:] if row and any(str(v or "").strip() for v in row)
                            and [str(v or "").strip() for v in row] != headers]
                    if rows:
                        tables.append({"headers": headers, "rows": rows, "page": number,
                                       "method": "native", "confidence": None})
                if sum(len(p["PDF text"]) for p in passages) > 1_000_000:
                    raise ValueError("PDF text exceeds the one-million-character limit; split the document.")
    if not passages and not tables:
        raise ValueError("No readable PDF text or OCR content found.")
    scanned = any(p["method"] != "native" for p in pages)
    if scanned:
        warnings.append("OCR text is source evidence, not a verified table. Supply verified tabular data before financial calculations; native tables alone may omit scanned figures.")
    metadata = {
        "pages": pages, "ocr_languages": "ara+eng",
        # Conservative: never calculate a partial total from native pages when
        # scanned pages may contain additional amounts or misaligned columns.
        "requires_numeric_review": scanned,
    }
    return {"tables": tables, "passages": passages, "metadata": metadata, "warnings": warnings}


if __name__ == "__main__":
    root = Path(sys.argv[1])
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (40, 40))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2, 16 * 1024**2))
        resource.setrlimit(resource.RLIMIT_NOFILE, (96, 96))
        result = _worker(root)
        payload = json.dumps(result, ensure_ascii=False)
        if len(payload.encode()) > MAX_OUTPUT:
            raise ValueError("PDF extraction exceeds the output limit; split the document.")
    except Exception as exc:
        payload = json.dumps({"error": f"Local PDF extraction failed: {exc}"})
    (root / "result").write_text(payload)
