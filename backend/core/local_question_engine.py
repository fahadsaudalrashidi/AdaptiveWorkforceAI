"""Small, deterministic analytics over already-ingested, governance-scanned tables.

This intentionally answers a narrow set of auditable aggregation and
document-retrieval questions. It does not execute user SQL/Python or ask a
language model to invent a calculation.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.core.local_query_plan import HELP, PlanError, execute_plan, parse_plan


_TOKEN = re.compile(r"[a-z0-9\u0600-\u06ff]+", re.I)
_STOP = {
    "a", "an", "and", "are", "by", "for", "from", "in", "is", "of", "our",
    "the", "to", "what", "which", "with", "show", "me", "give", "please",
    "data", "file", "report", "this", "all", "on", "per", "each", "among",
    "ما", "هو", "هي", "من", "في", "على", "عن", "الى", "إلى", "هذا", "هذه",
    "بيانات", "ملف", "الملف", "من فضلك", "مع", "كل", "حسب", "لكل",
}
_SENSITIVE = re.compile(
    r"(?:^|[^a-z0-9])(?:name|employee|person|phone|mobile|email|address|"
    r"national.?id|iqama|passport|iban|bank.?account|account.?number|"
    r"birth|dob|salary|راتب|اسم|هاتف|جوال|بريد|هوية|إقامة|اقامة|"
    r"جواز|آيبان|عنوان)(?:$|[^a-z0-9])",
    re.I,
)
_NUMERIC_DECORATION = re.compile(r"[\s\u066c$€£﷼SARsar%]")


@dataclass(frozen=True)
class LocalTableAnswer:
    text: str
    detail: str
    operation: str
    source_file: str
    rows: int
    columns: list[str]
    warnings: list[str]
    priority: bool = False
    query_audit: dict[str, Any] | None = None


def _tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", text).translate(
        str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    )
    return {token for token in _TOKEN.findall(text.lower()) if token not in _STOP}


def _safe_column(name: Any) -> bool:
    return not _SENSITIVE.search(str(name))


def _numeric_series(series: pd.Series) -> pd.Series | None:
    if pd.api.types.is_numeric_dtype(series):
        result = pd.to_numeric(series, errors="coerce")
    else:
        cleaned = series.astype("string").str.strip()
        cleaned = cleaned.str.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789."))
        cleaned = cleaned.str.replace("(", "-", regex=False).str.replace(")", "", regex=False)
        cleaned = cleaned.str.replace(_NUMERIC_DECORATION, "", regex=True)
        decimal_comma = cleaned.str.match(r"^-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{1,2}$", na=False)
        cleaned.loc[decimal_comma] = (
            cleaned.loc[decimal_comma].str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        )
        cleaned = cleaned.str.replace(",", "", regex=False)
        result = pd.to_numeric(cleaned, errors="coerce")
    if result.notna().sum() < max(1, int(series.notna().sum() * 0.9 + 0.999)):
        return None
    return result


def _match_columns(question: str, frame: pd.DataFrame, columns: list[str]) -> list[str]:
    asked = _tokens(question)
    ranked: list[tuple[int, int, str]] = []
    for column in columns:
        words = _tokens(str(column))
        if not words:
            continue
        overlap = len(words & asked)
        if words <= asked:
            ranked.append((2, overlap, column))
        elif overlap:
            ranked.append((1, overlap, column))
    if not ranked:
        return []
    best = max((exact, overlap) for exact, overlap, _ in ranked)
    return [column for exact, overlap, column in ranked if (exact, overlap) == best]


def analyze_local_question(
    question: str,
    files: dict[str, pd.DataFrame],
    pii_columns: dict[str, set[str]] | None = None,
) -> LocalTableAnswer | None:
    """Answer supported aggregation questions or extractive PDF-text queries.

    Returning None means the request is outside this intentionally limited
    interpreter; callers should preserve the existing allowlisted registry,
    knowledge search, and explicit unsupported response.
    """
    if not files:
        return None

    q = unicodedata.normalize("NFKC", question).strip()
    q_tokens = _tokens(q)
    raw_tokens = set(_TOKEN.findall(q.lower()))
    if not q_tokens:
        return None

    document_terms = {"summarize", "summary", "document", "document says", "text", "اكتب", "لخص", "لخصي", "المستند", "الوثيقة"}
    aggregate_words = {
        "sum", "total", "average", "mean", "count", "how", "many", "highest",
        "lowest", "largest", "smallest", "top", "bottom", "rank", "group",
        "compare", "trend", "sum", "overall", "average", "أعلى", "أقل",
        "متوسط", "مجموع", "إجمالي", "اجمالي", "عدد", "حسب", "اتجاه",
    }
    is_document_request = bool(q_tokens & document_terms)
    has_aggregation_intent = bool(
        (q_tokens & aggregate_words)
        or (raw_tokens & {"by", "per", "each", "group", "grouped", "trend", "حسب", "لكل"})
    )
    if has_aggregation_intent and not is_document_request and any(
        frame.attrs.get("pdf_extraction", {}).get("requires_numeric_review")
        for frame in files.values()
    ):
        return LocalTableAnswer(
            "Scanned PDF figures require clarification before calculations. Upload a verified CSV/Excel table or a clearer, verified searchable PDF; I won't calculate using uncertain OCR numbers or incomplete native tables.",
            "", "clarify", "", 0, [], [], priority=True,
        )

    # Explicit requests are parsed in full. Errors must never fall through to
    # an unfiltered aggregate or a domain-registry answer.
    if re.search(r'\b(where|compare|versus)\b|[<>=]', q, re.I) and (has_aggregation_intent or not is_document_request):
        try:
            plan = parse_plan(
                q, files,
                lambda source, columns: {
                    c for c in columns if not _safe_column(c)
                    or c in (pii_columns or {}).get(source, set())
                    or c in {"PDF page", "OCR confidence", "PDF extraction method", "PDF text"}
                },
            )
            selected = files[plan.source_file]
            if selected.attrs.get("pdf_extraction", {}).get("requires_numeric_review"):
                raise PlanError("Scanned PDF figures require verification before filtered calculations.")
            results, currency = execute_plan(plan, selected)
            audit = {
                "source_file": plan.source_file, "operation": plan.operation,
                "measure": plan.measure, "currency": currency,
                "cohorts": [result.to_dict() for result in results],
            }
            details = []
            for i, result in enumerate(results, 1):
                label = f"Cohort {i}" if len(results) == 2 else "Result"
                value = "No matching numeric records (no value calculated)" if result.value is None else f"{result.value:,.2f}"
                details.append(f"{label}: {value}")
            if currency:
                details.append(f"Source currency context: {currency} (no conversion; record counts are not monetary values).")
            if len(results) == 2 and all(r.value is not None for r in results):
                difference = results[0].value - results[1].value
                if not math.isfinite(difference):
                    raise PlanError("The comparison difference exceeds the supported numeric range.")
                details.append(f"Difference (cohort 1 minus cohort 2): {difference:,.2f}")
                audit["difference"] = difference
            return LocalTableAnswer(
                f'{"Comparison" if len(results) == 2 else "Filtered " + plan.operation} of {plan.measure or "records"} from {plan.source_file}.',
                "\n".join(details), "comparison" if len(results) == 2 else "filtered_" + plan.operation,
                plan.source_file, results[0].included_rows,
                [plan.measure] if plan.measure else [], [],
                query_audit=audit,
            )
        except PlanError as exc:
            return LocalTableAnswer(str(exc), "", "clarify", "", 0, [], [], priority=True)

    ranked_files: list[tuple[int, str, pd.DataFrame]] = []
    text_files = {
        filename: frame for filename, frame in files.items()
        if any(str(column).lower() == "pdf text" for column in frame.columns)
    }
    candidate_files = text_files if text_files and (is_document_request or not has_aggregation_intent) else files
    for filename, frame in candidate_files.items():
        name_tokens = _tokens(filename)
        column_tokens = set().union(*(_tokens(str(column)) for column in frame.columns)) if len(frame.columns) else set()
        ranked_files.append((len(name_tokens & q_tokens) + len(column_tokens & q_tokens), filename, frame))
    ranked_files.sort(key=lambda item: (-item[0], item[1]))

    if len(ranked_files) > 1 and ranked_files[0][0] == ranked_files[1][0]:
        return LocalTableAnswer(
            "I found multiple equally relevant uploaded files. Mention the file name in your question so I don't combine unrelated data.",
            "", "clarify", "", 0, [], [], priority=True,
        )
    _, filename, frame = ranked_files[0]
    excluded = set((pii_columns or {}).get(filename, set()))
    sensitive_columns = [
        str(column) for column in frame.columns
        if str(column) in excluded or not _safe_column(column)
    ]
    requested_sensitive_columns = _match_columns(question, frame, sensitive_columns)
    if requested_sensitive_columns:
        return LocalTableAnswer(
            "I can't answer using a detected personal-data column. Ask for a non-sensitive aggregate or remove personal identifiers from the source file.",
            f"Blocked columns: {', '.join(requested_sensitive_columns)}",
            "clarify", filename, len(frame), [], [], priority=True,
        )
    safe_columns = [str(c) for c in frame.columns if str(c) not in excluded and _safe_column(c)
                    and str(c) not in {"PDF page", "OCR confidence", "PDF extraction method"}]

    # Search only searchable PDF text, quoting source text rather than
    # summarizing or inferring its meaning.
    text_columns = [c for c in safe_columns if c.lower() == "pdf text"]
    if text_columns and (is_document_request or not has_aggregation_intent):
        terms = q_tokens - _tokens(filename) - {"summarize", "summary", "document", "text", "says", "لخص", "المستند", "الوثيقة"}
        matches: list[tuple[int, int, str]] = []
        for index, row in frame.iterrows():
            excerpt = str(row[text_columns[0]] or "").strip()
            if not excerpt:
                continue
            score = len(_tokens(excerpt) & terms) if terms else 1
            if score:
                page = row.get("PDF page", index + 1)
                matches.append((score, int(index), f"Page {page}: {excerpt[:700]}"))
        matches.sort(key=lambda item: (-item[0], item[1]))
        if matches:
            snippets = [entry[2] for entry in matches[:3]]
            return LocalTableAnswer(
                f"Extracted text passages from {filename}. These are source excerpts, not an AI-generated interpretation.",
                "\n\n".join(snippets), "document_search", filename, len(frame), safe_columns,
                ["PDF text may include local OCR. Review page confidence and verify figures against the original."]
                if frame.attrs.get("pdf_extraction") else ["Only searchable PDF text is available."],
            )
        if is_document_request:
            return LocalTableAnswer(
                f"Searchable text was extracted from {filename}, but no passage matched those terms.",
                "", "document_search", filename, len(frame), safe_columns,
                ["PDF text retrieval uses exact term overlap and does not infer meaning."],
            )

    if not has_aggregation_intent:
        return None

    count_intent = bool(raw_tokens & {"count", "many", "number", "عدد"})
    if re.search(r"\b(where|excluding|exclude|except|greater than|less than|above|below|between|only|after|before|since|until|during|versus|vs|join|ratio|median|percentile)\b|فقط|باستثناء", q, re.I):
        return LocalTableAnswer(
            "I couldn't safely interpret this condition or operation; I won't report an unfiltered result. " + HELP,
            "", "clarify", filename, len(frame), safe_columns, [], priority=True,
        )

    numeric_map = {
        str(column): _numeric_series(frame[column])
        for column in safe_columns
    }
    numeric_columns = [column for column, series in numeric_map.items() if series is not None]
    header_tokens = set().union(*(_tokens(column) for column in safe_columns)) if safe_columns else set()
    for column in safe_columns:
        if numeric_map[column] is not None or frame[column].nunique(dropna=True) > 100:
            continue
        for value in frame[column].dropna().unique():
            words = _tokens(str(value))
            if words and not words <= header_tokens and words <= q_tokens:
                return LocalTableAnswer(
                    "The question appears to select a category or date value. Row filtering is not supported in this local path yet; filter the source file first rather than relying on an unfiltered answer.",
                    "", "clarify", filename, len(frame), safe_columns, [], priority=True,
                )
    if not numeric_columns and not count_intent:
        return LocalTableAnswer(
            "This file has no columns with enough consistently numeric values for a reliable calculation. Check the extracted columns and number formats.",
            "", "clarify", filename, len(frame), safe_columns, [],
        )

    average_intent = bool(q_tokens & {"average", "mean", "typical", "متوسط"})
    sum_intent = bool(q_tokens & {"sum", "total", "how", "much", "overall", "مجموع", "اجمالي", "إجمالي"})
    top_intent = bool(raw_tokens & {"highest", "largest", "top", "most", "أعلى", "أكثر"})
    bottom_intent = bool(raw_tokens & {"lowest", "smallest", "bottom", "least", "أقل"})
    trend_intent = bool(raw_tokens & {"trend", "over", "month", "year", "time", "اتجاه"})
    by_intent = bool(raw_tokens & {"by", "per", "each", "group", "grouped", "حسب", "لكل", "بحسب"}) or trend_intent

    if not any((count_intent, average_intent, sum_intent, top_intent, bottom_intent, trend_intent)):
        if by_intent and _match_columns(q, frame, numeric_columns):
            sum_intent = True
        else:
            return None

    matched_numeric = _match_columns(q, frame, numeric_columns)
    if len(matched_numeric) > 1:
        return LocalTableAnswer(
            "The question could refer to more than one numeric column. Name the exact measure (for example, \"total Net Sales\").",
            f"Possible measures: {', '.join(matched_numeric[:10])}",
            "clarify", filename, len(frame), safe_columns, [], priority=True,
        )
    if not matched_numeric and not count_intent:
        return LocalTableAnswer(
            f"Please name the measure to calculate. Numeric columns: {', '.join(numeric_columns[:10])}",
            "", "clarify", filename, len(frame), safe_columns, [],
        )

    measure = None if count_intent else (matched_numeric[0] if matched_numeric else None)
    numeric_warnings = []
    if measure is not None:
        excluded_rows = len(frame) - int(numeric_map[measure].notna().sum())
        if excluded_rows:
            numeric_warnings.append(f"{excluded_rows:,} row(s) with missing or non-numeric {measure} were excluded.")
    dimension_candidates = [
        column for column in safe_columns
        if column not in numeric_columns and column not in (pii_columns or {}).get(filename, set())
        and frame[column].nunique(dropna=True) > 1
        and frame[column].nunique(dropna=True) <= min(50, max(2, int(len(frame) ** 0.5) + 1))
    ]
    dimensions = _match_columns(q, frame, dimension_candidates)
    if len(dimensions) > 1:
        return LocalTableAnswer(
            "Please name one grouping column; the question matches more than one.",
            f"Possible groupings: {', '.join(dimensions[:10])}",
            "clarify", filename, len(frame), safe_columns, [],
        )
    dimension = dimensions[0] if dimensions else None

    if by_intent and dimension is None and not trend_intent:
        return LocalTableAnswer(
            "I couldn't identify one unambiguous group-by column. Include its column name, such as \"by department\".",
            f"Available groupings: {', '.join(dimension_candidates[:10])}",
            "clarify", filename, len(frame), safe_columns, [],
        )

    if trend_intent:
        date_columns = [
            column for column in safe_columns
            if re.search(r"(date|period|month|year|time|تاريخ|فترة|شهر|سنة)", str(column), re.I)
        ]
        matched_dates = _match_columns(q, frame, date_columns)
        date_column = matched_dates[0] if len(matched_dates) == 1 else (date_columns[0] if len(date_columns) == 1 else None)
        if date_column is None:
            return LocalTableAnswer(
                f"I couldn't identify a single date or period column for a trend. Date-like columns: {', '.join(date_columns[:10]) or 'none detected'}.",
                "", "clarify", filename, len(frame), safe_columns, [],
            )
        date_strings = frame[date_column].dropna().astype(str)
        ambiguous = date_strings.str.extract(r"^(\d{1,2})[/-](\d{1,2})[/-]\d{2,4}$").dropna()
        if not ambiguous.empty:
            numbers = ambiguous.astype(int)
            if ((numbers[0] <= 12) & (numbers[1] <= 12) & (numbers[0] != numbers[1])).any():
                return LocalTableAnswer(
                    f"The {date_column} column has ambiguous day/month dates. Convert it to YYYY-MM-DD before requesting a trend.",
                    "", "clarify", filename, len(frame), safe_columns, [], priority=True,
                )
        dates = pd.to_datetime(frame[date_column], errors="coerce", dayfirst=False)
        valid = dates.notna()
        if not valid.any():
            return LocalTableAnswer(
                f"The {date_column} column contains no reliably parseable dates.",
                "", "clarify", filename, len(frame), safe_columns, [],
            )
        series = numeric_map[measure] if measure else None
        if series is None:
            return None
        valid = valid & series.notna()
        monthly = pd.DataFrame({"period": dates[valid].dt.to_period("M").astype(str), "value": series[valid]})
        grouped = monthly.groupby("period", sort=True)["value"].sum(min_count=1).dropna()
        detail = "\n".join(f"{period}: {value:,.2f}" for period, value in grouped.tail(12).items())
        return LocalTableAnswer(
            f"Monthly total of {measure} from {filename} based on {int(valid.sum())} rows with valid dates. Only the 12 most recent periods are shown.",
            detail, "trend", filename, int(valid.sum()), safe_columns, numeric_warnings,
        )

    if count_intent and measure is None:
        if dimension is None:
            return LocalTableAnswer(
                f"Record count in {filename}: {len(frame):,} rows.",
                f"{len(frame):,} rows · {len(safe_columns)} non-sensitive columns",
                "count", filename, len(frame), safe_columns, [],
            )
        counts = frame.groupby(dimension, dropna=True).size().sort_values(ascending=False).head(12)
        detail = "\n".join(f"{key}: {int(value):,} rows" for key, value in counts.items())
        return LocalTableAnswer(
            f"Record counts grouped by {dimension} in {filename}. Showing up to 12 groups.",
            detail, "count_by", filename, len(frame), safe_columns, [],
        )

    values = numeric_map[measure]
    if dimension:
        reduced = pd.DataFrame({"group": frame[dimension], "value": values})
        aggregation = "mean" if average_intent else "sum"
        groups = reduced.groupby("group", dropna=True)["value"]
        grouped = (groups.mean() if aggregation == "mean" else groups.sum(min_count=1)).dropna()
        grouped = grouped.sort_values(ascending=not (top_intent or bottom_intent)) if not (top_intent or bottom_intent) else grouped.sort_values(ascending=bottom_intent)
        grouped = grouped.head(12)
        detail = "\n".join(f"{key}: {value:,.2f}" for key, value in grouped.items())
        return LocalTableAnswer(
            f"{'Average' if average_intent else 'Total'} {measure} grouped by {dimension} in {filename}. Showing up to 12 groups.",
            detail, "grouped_average" if average_intent else "grouped_total",
            filename, int(values.notna().sum()), safe_columns, numeric_warnings,
        )

    if top_intent or bottom_intent:
        value = values.max() if top_intent else values.min()
        operation = "maximum" if top_intent else "minimum"
    elif average_intent:
        value, operation = values.mean(), "average"
    else:
        value, operation = values.sum(), "total"

    labels = {"maximum": "Maximum", "minimum": "Minimum", "average": "Average", "total": "Total"}
    return LocalTableAnswer(
        f"{labels[operation]} {measure} in {filename} from {int(values.notna().sum())} numeric records.",
        f"{labels[operation]} {measure}: {value:,.2f}",
        operation, filename, int(values.notna().sum()), safe_columns, numeric_warnings,
    )
