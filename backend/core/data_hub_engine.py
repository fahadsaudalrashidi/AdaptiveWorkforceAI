"""Request-scoped data profiling, anomaly checks, forecasting, and safe exports.

Uploaded files are parsed in memory and are never persisted by this module.
Responses contain schema and aggregate statistics only; source records are
never returned or included in generated workbooks/PDFs.
"""
from __future__ import annotations

import io
import re
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from backend.core.excel_ingestion_engine import ExcelIngestionEngine, IngestionResult
from backend.core.secure_file_ingestion import SecureFileIngestion

SUPPORTED_DATA_HUB_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}
CLEANING_OPTIONS = {
    "trim_text",
    "remove_blank_rows",
    "remove_blank_columns",
    "remove_exact_duplicates",
}
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_REQUEST_BYTES = 50 * 1024 * 1024
MAX_FILES_PER_REQUEST = 10

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_DATE_NAME = re.compile(r"(date|time|month|period|timestamp|تاريخ|شهر|فترة)", re.I)
_EXPIRY_NAME = re.compile(
    r"(expir|expiry|expires|valid.?until|contract.?end|end.?date|"
    r"iqama|visa|permit|تاريخ.?الانتهاء|انتهاء|صلاحية|نهاية.?العقد)",
    re.I,
)
_PAYROLL_NAME = re.compile(r"(payroll|salary|salar|gross|net.?pay|wage|overtime|بدل|راتب|أجر)", re.I)
_BUDGET_NAME = re.compile(r"(budget|actual|planned|forecast|ميزانية|فعلي|مخطط)", re.I)
_SAFE_LABEL_LIMIT = 160


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(number, 4) if np.isfinite(number) else None


def _clean_numeric(series: pd.Series) -> pd.Series:
    """Parse common financial formatting without changing source cells."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")

    def parse(value: Any) -> float:
        if pd.isna(value):
            return np.nan
        text = str(value).translate(_ARABIC_DIGITS).strip()
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1].strip()
        text = re.sub(r"(?i)\b(?:SAR|USD|EUR|GBP|AED)\b", "", text)
        for currency in ("ر.س", "ر س", "ريالات", "ريال", "دولار"):
            text = text.replace(currency, "")
        text = re.sub(r"[$£€٪%\s\u00a0]", "", text)
        # Accept comma decimals only when they are unambiguously not groups of
        # three digits; otherwise commas are treated as thousands separators.
        if "," in text and "." not in text:
            if text.count(",") == 1 and len(text.rsplit(",", 1)[1]) in {1, 2}:
                text = text.replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", "")
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
            return np.nan
        try:
            number = float(text)
            return -abs(number) if negative else number
        except ValueError:
            return np.nan

    return pd.Series((parse(value) for value in series), index=series.index, dtype="float64")


def _parse_dates(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    try:
        return pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=True)
    except (TypeError, ValueError):
        return pd.to_datetime(series, errors="coerce", dayfirst=True)


def _column_kind(series: pd.Series, name: str) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "empty"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    sample_text = non_null.head(100).astype(str).str.strip()
    date_shaped = sample_text.str.contains(
        r"(?:\d{4}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|"
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})",
        case=False,
        regex=True,
    )
    if _DATE_NAME.search(name) and date_shaped.mean() >= 0.8:
        parsed = _parse_dates(sample_text)
        if parsed.notna().mean() >= 0.8:
            return "date"
    numeric = _clean_numeric(non_null)
    if numeric.notna().mean() >= 0.9 and numeric.notna().sum() >= 2:
        return "numeric"
    if non_null.nunique(dropna=True) <= min(20, max(2, int(len(non_null) * 0.1))):
        return "categorical"
    sample = non_null.head(100).astype(str)
    return "text" if sample.str.len().mean() > 80 else "categorical"


def _sensitivity(name: str, scanner: SecureFileIngestion) -> tuple[bool, str | None]:
    classification = scanner._classify_column(str(name))
    if classification.classification in {"pii", "leakage"}:
        return True, classification.classification
    return False, None


def apply_cleaning(
    frame: pd.DataFrame,
    options: Iterable[str] = (),
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, int]]:
    """Apply only requested reversible/in-memory operations and report counts."""
    selected = set(options)
    unknown = selected - CLEANING_OPTIONS
    if unknown:
        raise ValueError(f"Unsupported cleaning option(s): {', '.join(sorted(unknown))}")

    result = frame.copy()
    applied: list[dict[str, Any]] = []
    before_rows, before_columns = len(result), len(result.columns)

    if "trim_text" in selected:
        changed_cells = 0
        for column in result.select_dtypes(include=["object", "string"]).columns:
            original = result[column]
            cleaned = original.map(lambda value: value.strip() if isinstance(value, str) else value)
            changed_cells += int((original.fillna("\0") != cleaned.fillna("\0")).sum())
            result[column] = cleaned
        applied.append({"id": "trim_text", "changed": changed_cells})

    if "remove_blank_rows" in selected:
        blank = result.apply(
            lambda col: col.isna() | col.astype("string").str.strip().eq("").fillna(False)
        ).all(axis=1)
        removed = int(blank.sum())
        result = result.loc[~blank].copy()
        applied.append({"id": "remove_blank_rows", "changed": removed})

    if "remove_blank_columns" in selected:
        blank_cols = [
            col for col in result.columns
            if result[col].isna().all()
            or result[col].astype("string").str.strip().eq("").fillna(False).all()
        ]
        result = result.drop(columns=blank_cols)
        applied.append({"id": "remove_blank_columns", "changed": len(blank_cols)})

    if "remove_exact_duplicates" in selected:
        before = len(result)
        result = result.drop_duplicates(keep="first").reset_index(drop=True)
        applied.append({"id": "remove_exact_duplicates", "changed": before - len(result)})

    counts = {
        "source_rows": before_rows,
        "analyzed_rows": len(result),
        "source_columns": before_columns,
        "analyzed_columns": len(result.columns),
    }
    return result.reset_index(drop=True), applied, counts


def _outlier_count(values: pd.Series) -> tuple[int, float | None, float | None]:
    values = values.dropna()
    if len(values) < 8:
        return 0, None, None
    q1, q3 = values.quantile([0.25, 0.75])
    iqr = float(q3 - q1)
    if not np.isfinite(iqr) or iqr <= 0:
        return 0, None, None
    low, high = float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)
    return int(((values < low) | (values > high)).sum()), _finite(low), _finite(high)


def _payroll_checks(frame: pd.DataFrame, sensitive: set[str]) -> list[dict[str, Any]]:
    """Return only cohort-level consistency counts; never expose row values."""
    if len(frame) < 10:
        return []
    columns = {str(c).strip().lower(): c for c in frame.columns}
    gross = next((c for key, c in columns.items() if "gross" in key and _PAYROLL_NAME.search(key)), None)
    net = next((c for key, c in columns.items() if "net" in key and _PAYROLL_NAME.search(key)), None)
    checks: list[dict[str, Any]] = []

    if gross is not None and net is not None:
        gross_values, net_values = _clean_numeric(frame[gross]), _clean_numeric(frame[net])
        valid = gross_values.notna() & net_values.notna()
        evaluated = int(valid.sum())
        if evaluated >= 10:
            violations = int((gross_values[valid] < net_values[valid]).sum())
            if violations:
                checks.append({
                    "id": "gross_below_net",
                    "kind": "payroll_consistency",
                    "column": f"{gross} / {net}",
                    "count": violations,
                    "evaluated": evaluated,
                    "percentage": _finite(violations * 100 / evaluated),
                    "severity": "high",
                    "method": "Gross pay is below net pay",
                })
    return checks


def _compliance_checks(frame: pd.DataFrame) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    today = pd.Timestamp(date.today())
    for column in frame.columns:
        if not _EXPIRY_NAME.search(str(column)):
            continue
        dates = _parse_dates(frame[column]).dropna()
        if dates.empty:
            continue
        expired = int((dates.dt.normalize() < today).sum())
        due_soon = int(((dates.dt.normalize() >= today) & (dates.dt.normalize() <= today + pd.Timedelta(days=30))).sum())
        if expired or due_soon:
            checks.append({
                "id": "compliance_expiry",
                "kind": "compliance",
                "column": str(column),
                "count": expired + due_soon,
                "expired": expired,
                "due_30_days": due_soon,
                "evaluated": int(len(dates)),
                "severity": "high" if expired else "moderate",
                "method": "Expiry dates compared with the server's current date",
            })
    return checks


def profile_frame(
    frame: pd.DataFrame,
    *,
    filename: str,
    sheet: str,
    cleaning_options: Iterable[str] = (),
) -> dict[str, Any]:
    scanner = SecureFileIngestion()
    cleaned, applied, counts = apply_cleaning(frame, cleaning_options)
    numeric_columns: list[dict[str, Any]] = []
    date_columns: list[str] = []
    columns: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    sensitive_columns: set[str] = set()
    missing_cells = 0

    for raw_name in cleaned.columns:
        name = str(raw_name)
        series = cleaned[raw_name]
        missing = int(series.isna().sum())
        missing_cells += missing
        kind = _column_kind(series, name)
        sensitive, sensitive_reason = _sensitivity(name, scanner)
        if sensitive:
            sensitive_columns.add(name)
        entry: dict[str, Any] = {
            "name": name[:_SAFE_LABEL_LIMIT],
            "dtype": str(series.dtype)[:40],
            "type": kind,
            "missing_count": missing,
            "missing_percent": _finite(missing * 100 / max(len(cleaned), 1)),
            "unique_count": int(series.nunique(dropna=True)),
            "sensitive": sensitive,
            "sensitive_reason": sensitive_reason,
        }
        if kind == "date":
            date_columns.append(name)
        if kind == "numeric":
            numeric = _clean_numeric(series)
            if not sensitive:
                valid = numeric.dropna()
                outliers, low, high = _outlier_count(valid)
                entry["numeric_summary"] = {
                    "non_null": int(len(valid)),
                    "mean": _finite(valid.mean()) if len(valid) else None,
                    "median": _finite(valid.median()) if len(valid) else None,
                    "min": _finite(valid.min()) if len(valid) else None,
                    "max": _finite(valid.max()) if len(valid) else None,
                    "std": _finite(valid.std()) if len(valid) > 1 else None,
                }
                entry["outlier_count"] = outliers
                numeric_columns.append({"name": name, "sensitive": False})
                if outliers:
                    rate = outliers * 100 / max(len(valid), 1)
                    anomalies.append({
                        "id": "numeric_outliers",
                        "kind": "distribution",
                        "column": name[:_SAFE_LABEL_LIMIT],
                        "count": outliers,
                        "evaluated": int(len(valid)),
                        "percentage": _finite(rate),
                        "severity": "high" if rate >= 10 else "moderate",
                        "method": "Tukey IQR fence (1.5 × IQR)",
                        "lower_fence": low,
                        "upper_fence": high,
                    })
            else:
                entry["numeric_summary"] = None
                entry["outlier_count"] = None
                numeric_columns.append({"name": name, "sensitive": True})
        columns.append(entry)

    anomalies.extend(_payroll_checks(cleaned, sensitive_columns))
    anomalies.extend(_compliance_checks(cleaned))

    duplicate_rows = int(cleaned.duplicated().sum())
    suggestions = [
        {"id": "trim_text", "eligible": True, "reason": "Trim leading/trailing spaces in text cells."},
        {"id": "remove_blank_rows", "eligible": int(cleaned.isna().all(axis=1).sum()), "reason": "Remove rows with no values."},
        {
            "id": "remove_blank_columns",
            "eligible": int(sum(
                col.isna().all() or col.astype("string").str.strip().eq("").fillna(False).all()
                for _, col in cleaned.items()
            )),
            "reason": "Remove columns containing no values.",
        },
        {"id": "remove_exact_duplicates", "eligible": duplicate_rows, "reason": "Remove exact duplicate rows only."},
    ]
    denominator = max(len(cleaned) * max(len(cleaned.columns), 1), 1)
    missing_percent = missing_cells * 100 / denominator
    duplicate_percent = duplicate_rows * 100 / max(len(cleaned), 1)
    quality = max(0.0, min(100.0, 100 - min(50, missing_percent * 0.75) - min(35, duplicate_percent * 0.5)))

    return {
        "id": f"{Path(filename).name}:{sheet}"[:240],
        "filename": Path(filename).name[:_SAFE_LABEL_LIMIT],
        "sheet": str(sheet)[:_SAFE_LABEL_LIMIT],
        "source_type": Path(filename).suffix.lower().lstrip("."),
        **counts,
        "column_count": len(columns),
        "missing_cells": missing_cells,
        "missing_percent": _finite(missing_percent),
        "duplicate_rows": duplicate_rows,
        "quality_score": _finite(quality),
        "columns": columns,
        "numeric_columns": numeric_columns,
        "date_columns": date_columns,
        "anomalies": anomalies,
        "cleaning_suggestions": suggestions,
        "applied_cleaning": applied,
        "warnings": [
            "Column names identified as sensitive are shown without value-level statistics.",
            "No source rows or individual employee values are returned or stored.",
            "Anomaly flags are review signals, not findings of misconduct or errors.",
        ],
    }


def profile_upload(
    raw: bytes,
    filename: str,
    cleaning_options: Iterable[str] = (),
) -> list[dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_DATA_HUB_EXTENSIONS:
        raise ValueError(f"Unsupported file type {suffix or '(no extension)'}. Use CSV, XLS, XLSX, or JSON.")
    if not raw:
        raise ValueError("The uploaded file is empty.")
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Each file must be 25 MB or smaller.")
    engine = ExcelIngestionEngine()
    results = engine.ingest_all(raw, Path(filename).name)
    profiles: list[dict[str, Any]] = []
    for sheet, result in results:
        if not result.success or result.df is None:
            raise ValueError(result.error or f"Could not read {sheet}.")
        if result.df.empty:
            continue
        profile = profile_frame(
            result.df, filename=filename, sheet=sheet, cleaning_options=cleaning_options
        )
        profile["warnings"] = list(dict.fromkeys(profile["warnings"] + result.warnings))
        profile["ingestion_transformations"] = result.transformations
        profiles.append(profile)
    if not profiles:
        raise ValueError("No non-empty tables or worksheets were found.")
    return profiles


def forecast_frame(
    frame: pd.DataFrame,
    *,
    filename: str,
    sheet: str,
    date_column: str,
    metric_column: str,
    aggregation: str = "sum",
    horizon: int = 3,
) -> dict[str, Any]:
    if aggregation not in {"sum", "mean", "count"}:
        raise ValueError("Aggregation must be sum, mean, or count.")
    if not 1 <= int(horizon) <= 12:
        raise ValueError("Forecast horizon must be between 1 and 12 months.")
    if date_column not in frame.columns:
        raise ValueError("Choose a date column present in the selected worksheet.")
    if metric_column != "__rows__" and metric_column not in frame.columns:
        raise ValueError("Choose a measure column present in the selected worksheet.")
    if metric_column == "__rows__" and aggregation != "count":
        raise ValueError("Record count requires the count aggregation.")
    if metric_column != "__rows__":
        sensitive, _ = _sensitivity(metric_column, SecureFileIngestion())
        if sensitive:
            raise ValueError("Forecasts are disabled for columns identified as personal or post-event data.")

    dates = _parse_dates(frame[date_column])
    values = pd.Series(1.0, index=frame.index) if metric_column == "__rows__" else _clean_numeric(frame[metric_column])
    valid = dates.notna() & values.notna()
    if not valid.any():
        raise ValueError("No rows have both a valid date and a numeric measure.")
    data = pd.DataFrame({"date": dates[valid], "value": values[valid]})
    data["period"] = data["date"].dt.to_period("M")
    grouped = data.groupby("period")["value"]
    if aggregation == "sum":
        monthly = grouped.sum()
    elif aggregation == "mean":
        monthly = grouped.mean()
    else:
        monthly = grouped.count().astype(float)
    monthly = monthly.sort_index()
    monthly = monthly[monthly.notna()]
    if len(monthly) < 8:
        raise ValueError(
            f"At least 8 monthly observations are required for a trend projection; found {len(monthly)}."
        )

    # Fit a transparent linear trend against calendar-month offsets. No seasonality,
    # causal factors, or external data are inferred.
    x = np.array([p.ordinal - monthly.index[0].ordinal for p in monthly.index], dtype=float)
    y = monthly.to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = intercept + slope * x
    residuals = y - fitted
    dof = len(y) - 2
    residual_se = float(np.sqrt(np.sum(residuals ** 2) / dof)) if dof > 0 else 0.0
    sxx = float(np.sum((x - x.mean()) ** 2))
    try:
        from scipy.stats import t as student_t
        critical = float(student_t.ppf(0.975, dof)) if dof > 0 else 1.96
    except Exception:
        critical = 1.96

    last_ordinal = monthly.index[-1].ordinal
    projection: list[dict[str, Any]] = []
    for offset in range(1, int(horizon) + 1):
        x_next = last_ordinal + offset - monthly.index[0].ordinal
        estimate = float(intercept + slope * x_next)
        prediction_se = residual_se * float(np.sqrt(1 + 1 / len(y) + ((x_next - x.mean()) ** 2 / sxx if sxx > 0 else 0)))
        margin = critical * prediction_se
        period = monthly.index[-1] + offset
        projection.append({
            "period": str(period),
            "estimate": _finite(estimate),
            "lower": _finite(estimate - margin),
            "upper": _finite(estimate + margin),
        })

    return {
        "filename": Path(filename).name[:_SAFE_LABEL_LIMIT],
        "sheet": str(sheet)[:_SAFE_LABEL_LIMIT],
        "date_column": date_column[:_SAFE_LABEL_LIMIT],
        "metric_column": "Record count" if metric_column == "__rows__" else metric_column[:_SAFE_LABEL_LIMIT],
        "aggregation": aggregation,
        "period_grain": "month",
        "method": "Ordinary least-squares linear trend with an approximate 95% prediction interval",
        "observation_count": int(len(monthly)),
        "observed": [{"period": str(period), "value": _finite(value)} for period, value in monthly.items()],
        "forecast": projection,
        "limitations": [
            "Exploratory trend projection only; it does not model seasonality, causal drivers, or future policy changes.",
            "Prediction intervals assume independent, approximately stable residuals and are not a guarantee.",
            "Validate against domain knowledge before using in workforce or financial decisions.",
        ],
    }


def build_summary_xlsx(profiles: list[dict[str, Any]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    def safe_text(value: Any) -> str:
        text = str(value if value is not None else "")[:32000]
        return "'" + text if text[:1] in {"=", "+", "-", "@"} else text

    workbook = Workbook()
    overview = workbook.active
    overview.title = "Overview"
    overview.append(["THRIVE Data Hub — Aggregate Summary"])
    overview.append(["Generated (UTC)", pd.Timestamp.now(tz="UTC").isoformat()])
    overview.append(["Privacy", "Schema and aggregate metrics only; no source records included."])
    overview.append(["Files / sheets", len(profiles)])
    overview.append(["Source rows", sum(int(item["source_rows"]) for item in profiles)])
    overview.append(["Analyzed rows", sum(int(item["analyzed_rows"]) for item in profiles)])

    schema = workbook.create_sheet("Data Profile")
    schema.append(["File", "Sheet", "Column", "Type", "Missing", "Missing %", "Unique", "Sensitive", "Mean", "Median", "Min", "Max", "Outlier count"])
    anomaly_sheet = workbook.create_sheet("Anomalies")
    anomaly_sheet.append(["File", "Sheet", "Signal", "Column", "Flagged", "Evaluated", "Rate %", "Severity", "Method"])
    cleaning_sheet = workbook.create_sheet("Cleaning Log")
    cleaning_sheet.append(["File", "Sheet", "Operation", "Cells / rows / columns changed"])
    for profile in profiles:
        for column in profile["columns"]:
            stats = column.get("numeric_summary") or {}
            schema.append([
                safe_text(profile["filename"]), safe_text(profile["sheet"]), safe_text(column["name"]),
                safe_text(column["type"]), int(column["missing_count"]), column["missing_percent"],
                int(column["unique_count"]), "Yes" if column["sensitive"] else "No",
                stats.get("mean"), stats.get("median"), stats.get("min"), stats.get("max"),
                column.get("outlier_count"),
            ])
        for anomaly in profile["anomalies"]:
            anomaly_sheet.append([
                safe_text(profile["filename"]), safe_text(profile["sheet"]), safe_text(anomaly["kind"]),
                safe_text(anomaly["column"]), int(anomaly["count"]), int(anomaly["evaluated"]),
                anomaly.get("percentage"), safe_text(anomaly["severity"]), safe_text(anomaly["method"]),
            ])
        for item in profile["applied_cleaning"]:
            cleaning_sheet.append([
                safe_text(profile["filename"]), safe_text(profile["sheet"]), safe_text(item["id"]), int(item["changed"]),
            ])

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="2E3070")
        for index, cells in enumerate(sheet.columns, start=1):
            width = min(42, max(12, max((len(str(cell.value or "")) for cell in list(cells)[:80]), default=10) + 2))
            sheet.column_dimensions[get_column_letter(index)].width = width
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def build_summary_pdf(profiles: list[dict[str, Any]], language: str = "en") -> bytes:
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError("PDF export is unavailable because fpdf2 is not installed.") from exc

    root = Path(__file__).resolve().parents[2]
    fonts = root / "executive-ui" / "public" / "brand" / "fonts"
    latin_regular = fonts / "font-0.ttf"
    latin_bold = fonts / "font-3.ttf"
    arabic_regular = fonts / "font-4.ttf"
    arabic_bold = fonts / "font-7.ttf"
    if not all(path.is_file() for path in (latin_regular, latin_bold, arabic_regular, arabic_bold)):
        raise RuntimeError("THRIVE report fonts are missing; PDF report cannot be generated.")

    is_ar = language == "ar"
    title = "تقرير مركز البيانات" if is_ar else "THRIVE Data Hub — Executive Summary"
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.add_font("ThriveLatin", style="", fname=str(latin_regular))
    pdf.add_font("ThriveLatin", style="B", fname=str(latin_bold))
    pdf.add_font("ThriveArabic", style="", fname=str(arabic_regular))
    pdf.add_font("ThriveArabic", style="B", fname=str(arabic_bold))

    font = "ThriveArabic" if is_ar else "ThriveLatin"
    def write(text: str, *, bold: bool = False, size: int = 10, height: int = 7) -> None:
        pdf.set_font(font, style="B" if bold else "", size=size)
        if is_ar:
            pdf.set_text_shaping(use_shaping_engine=True, direction="rtl", script="arab", language="ara")
        else:
            pdf.set_text_shaping(use_shaping_engine=False)
        pdf.multi_cell(0, height, text=str(text)[:800], align="R" if is_ar else "L")

    write(title, bold=True, size=17, height=12)
    write(
        "ملخصات مجمّعة فقط؛ لا يتضمن التقرير سجلات المصدر أو قيماً فردية."
        if is_ar else "Aggregate analysis only; source records and individual values are not included.",
        size=9,
    )
    write(
        f"عدد الملفات / الأوراق: {len(profiles)}"
        if is_ar else f"Files / worksheets: {len(profiles)}",
        bold=True,
    )
    for profile in profiles:
        pdf.ln(3)
        write(f"{profile['filename']} — {profile['sheet']}", bold=True, size=12, height=9)
        if is_ar:
            write(
                f"الصفوف المحللة: {profile['analyzed_rows']} | الأعمدة: {profile['column_count']} | "
                f"جودة البيانات الإرشادية: {profile['quality_score']}/100 | "
                f"إشارات المراجعة: {len(profile['anomalies'])}"
            )
        else:
            write(
                f"Analyzed rows: {profile['analyzed_rows']} | Columns: {profile['column_count']} | "
                f"Heuristic quality: {profile['quality_score']}/100 | Review signals: {len(profile['anomalies'])}"
            )
        for anomaly in profile["anomalies"][:20]:
            write(
                f"• {anomaly['kind']} — {anomaly['column']}: {anomaly['count']} / "
                f"{anomaly['evaluated']} ({anomaly.get('percentage') or 0}%) — {anomaly['method']}",
                size=9,
            )
        if profile["anomalies"]:
            write("Column-level anomaly counts are review signals, not source records.", size=8)
        for column in profile["columns"][:100]:
            if column["sensitive"]:
                description = f"{column['name']}: sensitive field; value statistics withheld."
            else:
                stats = column.get("numeric_summary") or {}
                description = (
                    f"{column['name']} ({column['type']}): {column['missing_count']} missing, "
                    f"{column['unique_count']} distinct"
                )
                if stats:
                    description += f", median {stats.get('median')}, range {stats.get('min')}–{stats.get('max')}"
            write(description, size=8, height=6)
    if is_ar:
        write("للاستخدام الاستكشافي؛ راجع المنهجية والقيود قبل اتخاذ القرار.", size=8)
    else:
        write("Exploratory analysis only. Review methods and limitations before decisions.", size=8)
    return bytes(pdf.output())
