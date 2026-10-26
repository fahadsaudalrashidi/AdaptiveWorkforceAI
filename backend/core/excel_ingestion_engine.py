"""
Excel / CSV / Parquet Ingestion Engine — Phase 9.

Handles safe parsing of HR datasets in multiple formats with Arabic/English
header support, multi-sheet selection, formula stripping, and encoding detection.

Design rules:
  - Never execute cell formulas
  - Preserve original headers in metadata
  - Log every transformation
  - Detect language from column names
  - Handle Arabic column names and boolean values
  - Choose the most HR-relevant sheet when multiple sheets exist
"""

from __future__ import annotations

import io
import json
import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── HR-relevance signal words ─────────────────────────────────────────────────

_HR_KEYWORDS_EN = {
    "employee", "emp", "staff", "worker", "person", "department", "dept",
    "salary", "attrition", "tenure", "hire", "job", "position", "performance",
    "manager", "training", "promotion", "leave", "absent", "resignation",
}

_HR_KEYWORDS_AR = {
    "موظف", "قسم", "راتب", "أداء", "مدير", "وظيفة", "تدريب", "استقالة",
    "الاستنزاف", "الدوران", "الراتب", "الخدمة",
}

_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")

_BOOL_TRUE_AR  = {"نعم", "صح", "صحيح", "حقيقي"}
_BOOL_FALSE_AR = {"لا", "خطأ", "كاذب"}


# ── Return type ───────────────────────────────────────────────────────────────

@dataclass
class IngestionResult:
    success: bool
    df: Optional[pd.DataFrame]
    row_count: int
    column_count: int
    original_headers: list[str]
    normalized_headers: list[str]
    detected_language: str          # 'en' | 'ar' | 'mixed'
    detected_erp_style: Optional[str]
    encoding_used: str
    sheet_used: Optional[str]
    warnings: list[str] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ── Engine ────────────────────────────────────────────────────────────────────

class ExcelIngestionEngine:
    """
    Safe ingestion of HR datasets in xlsx / xls / csv / parquet / json formats.

    Call:
        engine = ExcelIngestionEngine()
        result = engine.ingest(raw_bytes, filename)
    """

    SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".parquet", ".json", ".pdf"}

    def ingest(self, raw_bytes: bytes, filename: str, progress=None) -> IngestionResult:
        suffix = Path(filename).suffix.lower()
        if suffix not in self.SUPPORTED_EXTENSIONS:
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[],
                detected_language="unknown", detected_erp_style=None,
                encoding_used="none", sheet_used=None,
                error=f"Unsupported file type: {suffix!r}. Accepted: {sorted(self.SUPPORTED_EXTENSIONS)}",
            )

        if not raw_bytes:
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[],
                detected_language="unknown", detected_erp_style=None,
                encoding_used="none", sheet_used=None,
                error="File is empty.",
            )

        try:
            if suffix in (".xlsx", ".xls"):
                return self._load_excel(raw_bytes, filename)
            elif suffix == ".pdf":
                return self._load_pdf(raw_bytes, filename, progress=progress)
            elif suffix == ".csv":
                return self._load_csv(raw_bytes, filename)
            elif suffix == ".parquet":
                return self._load_parquet(raw_bytes)
            elif suffix == ".json":
                return self._load_json(raw_bytes)
        except Exception as exc:
            logger.exception("Ingestion failed for %s", filename)
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[],
                detected_language="unknown", detected_erp_style=None,
                encoding_used="none", sheet_used=None,
                error=str(exc),
            )

        return IngestionResult(  # unreachable guard
            success=False, df=None, row_count=0, column_count=0,
            original_headers=[], normalized_headers=[],
            detected_language="unknown", detected_erp_style=None,
            encoding_used="none", sheet_used=None,
            error="Internal routing error.",
        )

    def ingest_all(self, raw_bytes: bytes, filename: str, progress=None) -> list[tuple[str, IngestionResult]]:
        """Ingest every non-empty spreadsheet sheet; other formats return one frame."""
        suffix = Path(filename).suffix.lower()
        if suffix == ".json":
            try:
                parsed = json.loads(raw_bytes.decode("utf-8-sig"))
                collections = self._collect_json_record_lists(parsed)
                if len(collections) > 1:
                    return [
                        (path, self._finalize_from_df(
                            pd.json_normalize(items, sep="."), sheet_used=path, warnings=[],
                            transformations=[f"Flattened JSON records from {path}"],
                        ))
                        for path, items in collections
                    ]
            except Exception:
                pass  # ingest() below returns the explicit JSON parse error.
        if suffix not in {".xlsx", ".xls"}:
            result = self.ingest(raw_bytes, filename, progress=progress)
            if suffix == ".pdf" and result.success and result.df is not None:
                text_pages = result.df.attrs.get("pdf_text_pages")
                if text_pages:
                    text_result = self._finalize_from_df(
                        pd.DataFrame(text_pages), sheet_used="Document text",
                        warnings=list(result.warnings) + ["PDF passages are extracted quotations, not generated interpretations."],
                        transformations=["Extracted local PDF text with source page numbers"],
                    )
                    text_result.df.attrs["pdf_extraction"] = result.df.attrs.get("pdf_extraction", {})
                    return [("Tables", result), ("Document text", text_result)]
            return [(result.sheet_used or "Data", result)]
        if not raw_bytes:
            return [("Workbook", self.ingest(raw_bytes, filename))]

        results: list[tuple[str, IngestionResult]] = []
        try:
            if suffix == ".xlsx":
                import openpyxl
                workbook = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True, read_only=True)
                try:
                    if len(workbook.sheetnames) > 50:
                        raise ValueError("The workbook has more than 50 sheets; split it before analysis.")
                    for sheet_name in workbook.sheetnames:
                        rows = workbook[sheet_name].iter_rows(values_only=True)
                        header_row = None
                        frame_rows: list[tuple] = []
                        for row in rows:
                            if header_row is None:
                                if any(value is not None and str(value).strip() for value in row):
                                    header_row = row
                                continue
                            frame_rows.append(row)
                        if header_row is None:
                            continue
                        headers = [
                            str(value).strip() if value is not None and str(value).strip() else f"Column {index + 1}"
                            for index, value in enumerate(header_row)
                        ]
                        frame_rows = [
                            row[:len(headers)] + (None,) * max(0, len(headers) - len(row))
                            for row in frame_rows
                            if any(value is not None and str(value).strip() for value in row)
                        ]
                        if not frame_rows:
                            continue
                        df = pd.DataFrame(frame_rows, columns=headers)
                        result = self._finalize_from_df(
                            df, sheet_used=sheet_name, warnings=[], transformations=[f"Loaded worksheet: {sheet_name}"]
                        )
                        results.append((sheet_name, result))
                finally:
                    workbook.close()
            else:
                with pd.ExcelFile(io.BytesIO(raw_bytes)) as workbook:
                    if len(workbook.sheet_names) > 50:
                        raise ValueError("The workbook has more than 50 sheets; split it before analysis.")
                    for sheet_name in workbook.sheet_names:
                        frame = workbook.parse(sheet_name=sheet_name)
                        if frame.empty:
                            continue
                        result = self._finalize_from_df(
                            frame, sheet_used=sheet_name, warnings=[], transformations=[f"Loaded worksheet: {sheet_name}"]
                        )
                        results.append((sheet_name, result))
        except Exception as exc:
            logger.warning("Could not ingest workbook sheets from %s: %s", filename, exc)
            return [("Workbook", IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[], detected_language="unknown",
                detected_erp_style=None, encoding_used="binary", sheet_used=None,
                error=f"Could not analyze all workbook sheets: {exc}",
            ))]

        if not results:
            failed = self.ingest(raw_bytes, filename)
            if failed.success:
                return [(failed.sheet_used or "Sheet 1", failed)]
            return [("Workbook", failed)]
        return results

    # ── Excel ─────────────────────────────────────────────────────────────────

    def _load_excel(self, raw_bytes: bytes, filename: str) -> IngestionResult:
        import openpyxl
        warnings: list[str] = []
        transformations: list[str] = []

        try:
            wb = openpyxl.load_workbook(
                io.BytesIO(raw_bytes),
                data_only=True,     # get computed values, not formulas
                read_only=False,
            )
        except Exception as exc:
            try:
                # xls fallback via pandas xlrd
                df = pd.read_excel(io.BytesIO(raw_bytes), engine="xlrd")
                return self._finalize_from_df(df, sheet_used="sheet1", warnings=warnings, transformations=transformations)
            except Exception:
                return IngestionResult(
                    success=False, df=None, row_count=0, column_count=0,
                    original_headers=[], normalized_headers=[],
                    detected_language="unknown", detected_erp_style=None,
                    encoding_used="utf-8", sheet_used=None,
                    error=f"Cannot open Excel file: {exc}",
                )

        sheet_names = wb.sheetnames
        if len(sheet_names) == 0:
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[],
                detected_language="unknown", detected_erp_style=None,
                encoding_used="utf-8", sheet_used=None,
                error="Excel file contains no sheets.",
            )

        sheet_name = self._choose_best_sheet(wb, sheet_names)
        if len(sheet_names) > 1:
            warnings.append(
                f"Multiple sheets detected ({sheet_names}). "
                f"Auto-selected '{sheet_name}' as most HR-relevant."
            )
            transformations.append(f"Sheet selected: {sheet_name!r}")

        ws = wb[sheet_name]

        # Detect hidden rows
        hidden_rows = sum(
            1 for row in ws.row_dimensions.values()
            if getattr(row, "hidden", False)
        )
        if hidden_rows > 0:
            warnings.append(f"{hidden_rows} hidden row(s) detected in sheet. These will be included.")

        # Build DataFrame from worksheet (data_only=True strips formulas)
        data = list(ws.values)
        if not data:
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[],
                detected_language="unknown", detected_erp_style=None,
                encoding_used="utf-8", sheet_used=sheet_name,
                error="Selected sheet is empty.",
            )

        # Find first non-empty row as header
        header_row_idx = 0
        for i, row in enumerate(data):
            if any(cell is not None and str(cell).strip() for cell in row):
                header_row_idx = i
                break

        if header_row_idx > 0:
            warnings.append(f"Skipped {header_row_idx} empty top row(s) before header.")
            transformations.append(f"Skipped {header_row_idx} leading empty rows")

        raw_headers = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(data[header_row_idx])]
        rows = data[header_row_idx + 1:]

        if not rows:
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=raw_headers, normalized_headers=raw_headers,
                detected_language=self._detect_language(raw_headers),
                detected_erp_style=None,
                encoding_used="utf-8", sheet_used=sheet_name,
                error="Sheet has headers but no data rows.",
            )

        df = pd.DataFrame(rows, columns=raw_headers)

        # Normalize Arabic booleans
        for col in df.select_dtypes(include="object").columns:
            series_lower = df[col].astype(str).str.strip().str.lower()
            if series_lower.isin(_BOOL_TRUE_AR | _BOOL_FALSE_AR | {"نعم", "لا"}).any():
                df[col] = df[col].map(
                    lambda v: True if str(v).strip() in _BOOL_TRUE_AR else
                              (False if str(v).strip() in _BOOL_FALSE_AR else v)
                )
                transformations.append(f"Normalized Arabic booleans in column '{col}'")

        return self._finalize_from_df(
            df, sheet_used=sheet_name, warnings=warnings, transformations=transformations
        )

    # ── CSV ───────────────────────────────────────────────────────────────────

    def _load_csv(self, raw_bytes: bytes, filename: str) -> IngestionResult:
        warnings: list[str] = []
        transformations: list[str] = []

        # Try multiple encodings in order
        encodings = ["utf-8-sig", "utf-8", "cp1256", "windows-1256", "latin-1"]
        df = None
        encoding_used = "unknown"

        for enc in encodings:
            try:
                sample = raw_bytes.decode(enc)
                try:
                    delimiter = csv.Sniffer().sniff(sample[:65536], delimiters=",;\t|").delimiter
                except csv.Error:
                    delimiter = ","
                df = pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, sep=delimiter)
                transformations.append(f"CSV delimiter: {delimiter!r}")
                encoding_used = enc
                if enc != "utf-8":
                    transformations.append(f"CSV decoded with encoding: {enc}")
                break
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue

        if df is None:
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[],
                detected_language="unknown", detected_erp_style=None,
                encoding_used="unknown", sheet_used=None,
                error="CSV encoding not detected. Try saving as UTF-8.",
            )

        return self._finalize_from_df(
            df, sheet_used=None, warnings=warnings,
            transformations=transformations, encoding_used=encoding_used
        )

    # ── Parquet ───────────────────────────────────────────────────────────────

    def _load_parquet(self, raw_bytes: bytes) -> IngestionResult:
        try:
            df = pd.read_parquet(io.BytesIO(raw_bytes))
        except Exception as exc:
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[],
                detected_language="unknown", detected_erp_style=None,
                encoding_used="binary", sheet_used=None,
                error=f"Cannot parse parquet: {exc}",
            )
        return self._finalize_from_df(df, sheet_used=None, warnings=[], transformations=["Loaded from Parquet"], encoding_used="binary")

    # ── JSON ──────────────────────────────────────────────────────────────────

    def _load_json(self, raw_bytes: bytes) -> IngestionResult:
        try:
            parsed = json.loads(raw_bytes.decode("utf-8-sig"))
            transformations = ["Loaded from JSON"]
            if isinstance(parsed, list):
                df = pd.json_normalize(parsed) if parsed and all(isinstance(item, dict) for item in parsed) else pd.DataFrame({"value": parsed})
            elif isinstance(parsed, dict):
                records = self._find_json_record_list(parsed)
                if records is not None:
                    path, items = records
                    df = pd.json_normalize(items, sep=".")
                    transformations.append(f"Flattened JSON records from {path}")
                elif parsed and all(isinstance(value, list) for value in parsed.values()) and len({len(value) for value in parsed.values()}) == 1:
                    df = pd.DataFrame(parsed)
                elif parsed and all(isinstance(value, dict) for value in parsed.values()):
                    df = pd.json_normalize(list(parsed.values()), sep=".")
                    df.insert(0, "record_id", list(parsed.keys()))
                    transformations.append("Flattened JSON objects keyed by record ID")
                else:
                    df = pd.json_normalize(parsed, sep=".")
            else:
                df = pd.DataFrame({"value": [parsed]})
        except Exception as exc:
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[],
                detected_language="unknown", detected_erp_style=None,
                encoding_used="utf-8", sheet_used=None,
                error=f"Cannot parse JSON: {exc}",
            )
        return self._finalize_from_df(df, sheet_used=None, warnings=[], transformations=transformations, encoding_used="utf-8")

    @staticmethod
    def _collect_json_record_lists(value: Any, path: str = "$") -> list[tuple[str, list[dict[str, Any]]]]:
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            return [(path, value)]
        if isinstance(value, dict):
            collections = []
            for key, child in value.items():
                collections.extend(ExcelIngestionEngine._collect_json_record_lists(child, f"{path}.{key}"))
            return collections
        return []

    @staticmethod
    def _find_json_record_list(value: Any, path: str = "$") -> Optional[tuple[str, list[dict[str, Any]]]]:
        """Find the first non-empty nested list of objects to use as records."""
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if isinstance(child, list) and child and all(isinstance(item, dict) for item in child):
                    return child_path, child
            for key, child in value.items():
                found = ExcelIngestionEngine._find_json_record_list(child, f"{path}.{key}")
                if found is not None:
                    return found
        elif isinstance(value, list):
            for index, child in enumerate(value):
                found = ExcelIngestionEngine._find_json_record_list(child, f"{path}[{index}]")
                if found is not None:
                    return found
        return None

    # ── PDF ──────────────────────────────────────────────────────────────────

    def _load_pdf(self, raw_bytes: bytes, filename: str, progress=None) -> IngestionResult:
        """Extract native tables and page-cited OCR text in a bounded local worker."""
        from backend.core.local_pdf_ocr import extract_pdf

        extracted = extract_pdf(raw_bytes, progress=progress)
        tables = []
        for table in extracted["tables"]:
            frame = pd.DataFrame(table["rows"], columns=table["headers"])
            frame["PDF page"] = table["page"]
            frame["PDF extraction method"] = table["method"]
            tables.append(frame)
        text_pages = extracted["passages"]

        if tables:
            df = pd.concat(tables, ignore_index=True, sort=False)
            warnings = ["Extracted PDF table text locally. Verify column alignment and values against the source document."] + extracted["warnings"]
            transformations = ["Extracted tables locally with pdfplumber", "Added source PDF page numbers"]
        elif text_pages:
            df = pd.DataFrame(text_pages)
            warnings = ["No native tables were found. Extracted page-cited PDF text locally."] + extracted["warnings"]
            transformations = ["Extracted PDF text with pdfplumber and offline Tesseract ara+eng as needed"]
        else:
            return IngestionResult(
                success=False, df=None, row_count=0, column_count=0,
                original_headers=[], normalized_headers=[],
                detected_language="unknown", detected_erp_style=None,
                encoding_used="binary", sheet_used=None,
                error="No searchable text or tables were found. The PDF may be scanned; local OCR is not configured.",
            )

        result = self._finalize_from_df(
            df, sheet_used=None, warnings=warnings, transformations=transformations,
            encoding_used="binary",
        )
        if tables and text_pages and result.df is not None:
            result.df.attrs["pdf_text_pages"] = text_pages
        if result.df is not None:
            result.df.attrs["pdf_extraction"] = extracted["metadata"]
        return result

    # ── Common finalization ───────────────────────────────────────────────────

    def _finalize_from_df(
        self,
        df: pd.DataFrame,
        sheet_used: Optional[str],
        warnings: list[str],
        transformations: list[str],
        encoding_used: str = "utf-8",
    ) -> IngestionResult:
        original_headers = list(df.columns.astype(str))

        # Handle duplicate columns
        if len(original_headers) != len(set(original_headers)):
            seen: dict[str, int] = {}
            new_cols = []
            for col in original_headers:
                if col in seen:
                    seen[col] += 1
                    new_cols.append(f"{col}_{seen[col]}")
                    warnings.append(f"Duplicate column '{col}' renamed to '{col}_{seen[col]}'")
                    transformations.append(f"Renamed duplicate column: {col} → {col}_{seen[col]}")
                else:
                    seen[col] = 0
                    new_cols.append(col)
            df.columns = new_cols

        # Normalize header strings (strip whitespace)
        normalized = [h.strip() for h in list(df.columns.astype(str))]
        if normalized != list(df.columns.astype(str)):
            transformations.append("Stripped whitespace from column names")
            df.columns = normalized

        # Parse salary columns with currency/comma formatting
        for col in df.columns:
            col_lower = col.lower()
            if any(kw in col_lower for kw in ("salary", "راتب", "income", "pay", "compensation")):
                if df[col].dtype == object:
                    cleaned = df[col].astype(str).str.replace(r"[, \s]", "", regex=True)
                    cleaned = cleaned.str.replace(r"[^\d.\-]", "", regex=True)
                    try:
                        df[col] = pd.to_numeric(cleaned, errors="coerce")
                        transformations.append(f"Normalized salary column '{col}' (removed currency/commas)")
                    except Exception:
                        pass

        detected_lang = self._detect_language(list(df.columns.astype(str)))
        detected_erp = self._detect_erp_style(list(df.columns.astype(str)))

        return IngestionResult(
            success=True,
            df=df,
            row_count=len(df),
            column_count=len(df.columns),
            original_headers=original_headers,
            normalized_headers=list(df.columns.astype(str)),
            detected_language=detected_lang,
            detected_erp_style=detected_erp,
            encoding_used=encoding_used,
            sheet_used=sheet_used,
            warnings=warnings,
            transformations=transformations,
        )

    # ── Helper: sheet selection ───────────────────────────────────────────────

    def _choose_best_sheet(self, wb: "openpyxl.Workbook", sheet_names: list[str]) -> str:
        if len(sheet_names) == 1:
            return sheet_names[0]

        best_sheet = sheet_names[0]
        best_score = -1

        for name in sheet_names:
            score = 0
            name_lower = name.lower()
            # Prefer sheets named like HR data
            hr_sheet_keywords = {"employee", "emp", "hr", "staff", "data", "موظف", "البيانات"}
            for kw in hr_sheet_keywords:
                if kw in name_lower:
                    score += 3

            # Check how many HR-like column names the sheet has
            ws = wb[name]
            headers = []
            for cell in next(ws.iter_rows(max_row=1, values_only=True), []):
                if cell is not None:
                    headers.append(str(cell).lower())

            for h in headers:
                if any(kw in h for kw in _HR_KEYWORDS_EN):
                    score += 1
                if any(kw in h for kw in _HR_KEYWORDS_AR):
                    score += 1

            if score > best_score:
                best_score = score
                best_sheet = name

        return best_sheet

    # ── Helper: language detection ────────────────────────────────────────────

    def _detect_language(self, headers: list[str]) -> str:
        arabic_count = sum(1 for h in headers if _ARABIC_RE.search(h))
        english_count = sum(1 for h in headers if re.search(r"[a-zA-Z]", h))

        if arabic_count == 0 and english_count == 0:
            return "unknown"
        if arabic_count > 0 and english_count > 0:
            return "mixed"
        if arabic_count > english_count:
            return "ar"
        return "en"

    # ── Helper: ERP detection ─────────────────────────────────────────────────

    def _detect_erp_style(self, headers: list[str]) -> Optional[str]:
        headers_lower = " ".join(h.lower() for h in headers)

        if any(kw in headers_lower for kw in ("workday", "wd_", "worker_id")):
            return "Workday"
        if any(kw in headers_lower for kw in ("successfactors", "sf_", "ecf_")):
            return "SAP SuccessFactors"
        if any(kw in headers_lower for kw in ("oracle", "hcm_", "person_number")):
            return "Oracle HCM"
        if any(kw in headers_lower for kw in ("mudad", "مدد", "الراتب_الأساسي")):
            return "Mudad (Saudi Payroll)"
        if any(kw in headers_lower for kw in ("qiwa", "qiwa_", "saudization")):
            return "Qiwa (Saudi Labour)"
        if any(kw in headers_lower for kw in ("bamboohr", "bamboo")):
            return "BambooHR"

        return None
