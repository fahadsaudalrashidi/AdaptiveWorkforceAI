"""Local, schema-grounded analytics over governance-scanned uploaded tables.

Natural language is translated into bounded pandas operations. This module
never executes user SQL/Python or asks a language model to invent a calculation.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.core.local_query_plan import HELP, PlanError, execute_plan, parse_plan


_TOKEN = re.compile(
    r"[a-z0-9\u0621-\u063a\u0641-\u064a\u0660-\u0669\u0671-\u06d3\u06fa-\u06fc]+",
    re.I,
)
_ARABIC_MARKS = re.compile(r"[\u064b-\u065f\u0670\u0640]")
_ARABIC_TRANSLATION = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي",
})
_STOP = {
    "a", "an", "and", "are", "by", "for", "from", "in", "is", "of", "our",
    "the", "to", "what", "which", "with", "show", "me", "give", "please",
    "data", "file", "report", "this", "all", "on", "per", "each", "among",
    "has", "have", "do", "does", "there", "was", "were",
    "ما", "هو", "هي", "من", "في", "على", "عن", "الى", "إلى", "هذا", "هذه",
    "بيانات", "ملف", "الملف", "فضلك", "مع", "كل", "حسب", "لكل",
    "هل", "ماهي", "ماهو", "ماذا", "اعطني", "اريد", "رجاء",
}
_COUNT_TERMS = {"count", "many", "number", "records", "rows", "عدد", "كم", "احصاء", "احصي"}
_SUM_TERMS = {"sum", "total", "overall", "amount", "مجموع", "اجمالي", "قيمة", "قيمه"}
_AVERAGE_TERMS = {"average", "avg", "mean", "typical", "متوسط", "معدل"}
_TOP_TERMS = {"highest", "largest", "top", "most", "maximum", "max", "اعلي", "الاكثر", "اكثر", "اكبر"}
_BOTTOM_TERMS = {"lowest", "smallest", "bottom", "least", "minimum", "min", "اقل", "ادني", "اصغر"}
_TREND_TERMS = {"trend", "trending", "over time", "month", "monthly", "year", "yearly", "time", "اتجاه", "شهريا", "شهري", "سنويا", "سنوي"}
_GROUP_TERMS = {"by", "per", "each", "group", "grouped", "breakdown", "distribution", "حسب", "لكل", "بحسب", "توزيع", "تصنيف", "تقسيم"}
_RECORD_TERMS = {
    "contract", "contracts", "invoice", "invoices", "employee", "employees",
    "staff", "person", "people", "records", "rows", "عقد", "عقود", "موظف",
    "موظفين", "عامل", "عمال", "سجل", "سجلات",
}
_SEMANTIC_ALIASES = {
    "payroll": (
        "payroll", "salary", "salaries", "wage", "wages", "compensation",
        "إجمالي الرواتب", "الرواتب", "راتب", "أجور",
    ),
    "expense": (
        "expense", "expenses", "cost", "costs", "spend", "spending",
        "expenditure", "مصروف", "مصروفات", "مصاريف", "تكلفة", "تكاليف",
        "إنفاق",
    ),
    "profit": ("profit", "profits", "ربح", "أرباح", "الربح"),
    "net_profit": (
        "net profit", "net income", "صافي الربح", "الربح الصافي", "صافي الدخل",
    ),
    "revenue": (
        "revenue", "sales", "turnover", "income", "مبيعات", "إيراد",
        "إيرادات", "دخل", "عائد",
    ),
    "amount": ("amount", "value", "مبلغ", "مبالغ", "قيمة", "قيم"),
    "department": (
        "department", "dept", "division", "business unit", "team",
        "قسم", "أقسام", "إدارة", "إدارات", "قطاع",
    ),
    "category": (
        "category", "classification", "class", "type", "فئة", "فئات",
        "تصنيف", "نوع",
    ),
    "headcount": (
        "headcount", "employee count", "staff count", "employees", "employee",
        "staff", "عدد الموظفين", "موظف", "موظفين", "عاملين",
    ),
}
_FINANCIAL_MEASURE_CONCEPTS = {"payroll", "expense", "profit", "net_profit", "revenue"}
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
    text = _ARABIC_MARKS.sub("", text).translate(_ARABIC_TRANSLATION).lower()
    result: set[str] = set()
    for token in _TOKEN.findall(text):
        if token in _STOP:
            continue
        if re.search(r"[\u0600-\u06ff]", token):
            if token.startswith("ال") and len(token) > 4:
                token = token[2:]
            if token.endswith("ية") and len(token) > 4:
                token = token[:-2] + "ي"
            if token == "عقود":
                token = "عقد"
        result.add(token)
    return result


def _language_is_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", text))


def _localized(question: str, english: str, arabic: str) -> str:
    return arabic if _language_is_arabic(question) else english


def _safe_column(name: Any) -> bool:
    return not _SENSITIVE.search(str(name))


def _semantic_concepts(text: str) -> set[str]:
    tokens = _tokens(text)
    return {
        concept
        for concept, aliases in _SEMANTIC_ALIASES.items()
        if any(_tokens(alias) <= tokens for alias in aliases)
    }


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
    asked_concepts = _semantic_concepts(question)
    ranked: list[tuple[int, int, str]] = []
    for column in columns:
        words = _tokens(str(column))
        if not words:
            continue
        overlap = len(words & asked)
        if words <= asked:
            ranked.append((3, overlap, column))
        elif overlap:
            ranked.append((2, overlap, column))
        else:
            semantic_overlap = len(_semantic_concepts(str(column)) & asked_concepts)
            if semantic_overlap:
                ranked.append((1, semantic_overlap, column))
            elif (
                len(columns) == 1
                and _semantic_concepts(str(column)) & {"amount"}
                and asked_concepts & _FINANCIAL_MEASURE_CONCEPTS
            ):
                # A generic money field may stand in for the requested financial
                # concept only when it is the sole eligible numeric measure.
                ranked.append((0, 1, column))
    if not ranked:
        return []
    best = max((exact, overlap) for exact, overlap, _ in ranked)
    return [column for exact, overlap, column in ranked if (exact, overlap) == best]


def _natural_category_filters(
    question: str,
    frame: pd.DataFrame,
    columns: list[str],
) -> tuple[list[tuple[str, str, str]], list[tuple[str, list[str]]]]:
    """Find exact observed low-cardinality text values named in the question.

    No fuzzy matching is used: a selected category must be present in the
    uploaded data and its normalized tokens must appear in the question.
    """
    asked = _tokens(question)
    operation_words = (
        _COUNT_TERMS | _SUM_TERMS | _AVERAGE_TERMS | _TOP_TERMS
        | _BOTTOM_TERMS | _TREND_TERMS | _GROUP_TERMS
    )
    raw_words = set(_TOKEN.findall(question.lower()))
    grouping_intent = bool(asked & (_GROUP_TERMS - {"by", "per", "each"})) or bool(
        raw_words & {"by", "per", "each", "حسب", "لكل", "كل"}
    )
    explicit_filter_cue = bool(
        raw_words & {"for", "in", "where", "only", "with", "في", "لدى", "فقط"}
        or asked & {"في", "فقط", "لدى", "ل"}
    )
    numeric_columns = [
        str(column) for column in columns
        if _numeric_series(frame[column]) is not None
    ]
    matched_measures = _match_columns(question, frame, numeric_columns) if numeric_columns else []
    measure_tokens = set().union(*(_tokens(column) for column in matched_measures)) if matched_measures else set()
    if len(matched_measures) == 1 and _semantic_concepts(matched_measures[0]) & {"amount"}:
        requested_financial_concepts = _semantic_concepts(question) & _FINANCIAL_MEASURE_CONCEPTS
        measure_tokens |= set().union(*(
            _tokens(alias)
            for concept in requested_financial_concepts
            for alias in _SEMANTIC_ALIASES[concept]
        )) if requested_financial_concepts else set()
    negative = bool(asked & {"not", "without", "غير", "ليس", "ليست", "بدون"})
    candidates: dict[str, set[str]] = {}
    for column in columns:
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
            continue
        values = series.dropna().unique()
        if not values.size or len(values) > 100:
            continue
        column_tokens = _tokens(str(column))
        for raw_value in values:
            if not isinstance(raw_value, str):
                continue
            value = raw_value.strip()
            value_tokens = _tokens(value)
            if not value_tokens or len(value_tokens) > 6:
                continue
            ignored_measure_tokens = measure_tokens if grouping_intent or not explicit_filter_cue else set()
            discriminating = value_tokens - column_tokens - operation_words - ignored_measure_tokens
            if discriminating and value_tokens <= asked:
                candidates.setdefault(column, set()).add(value)

    explicit_columns = [
        column for column in columns
        if _tokens(str(column)) and _tokens(str(column)) <= asked
    ]
    cross_column_ambiguity: list[tuple[str, list[str]]] = []
    for value in {value for values in candidates.values() for value in values}:
        matching_columns = [column for column, values in candidates.items() if value in values]
        if len(matching_columns) < 2:
            continue
        named_columns = [column for column in matching_columns if column in explicit_columns]
        if len(named_columns) == 1:
            for column in matching_columns:
                if column != named_columns[0]:
                    candidates[column].discard(value)
        else:
            cross_column_ambiguity.extend((column, [value]) for column in matching_columns)

    candidates = {column: values for column, values in candidates.items() if values}
    ambiguous = [
        (column, sorted(values))
        for column, values in candidates.items()
        if len(values) > 1
    ]
    ambiguous.extend(cross_column_ambiguity)
    if ambiguous:
        return [], ambiguous
    filters = [
        (column, "!=" if negative else "=", next(iter(values)))
        for column, values in candidates.items()
    ]
    return filters, []


def _build_filter_audit(
    filename: str,
    operation: str,
    measure: str | None,
    source: pd.DataFrame,
    selected: pd.DataFrame,
    filters: list[dict[str, Any]],
    missing_filter_rows: int,
    included_rows: int,
    value: float | int | None = None,
) -> dict[str, Any]:
    matched_rows = len(selected)
    return {
        "source_file": filename,
        "operation": operation,
        "measure": measure,
        "currency": None,
        "cohorts": [{
            "filters": filters,
            "source_rows": len(source),
            "matched_rows": matched_rows,
            "included_rows": included_rows,
            "excluded_rows": len(source) - included_rows,
            "missing_filter_rows": missing_filter_rows,
            "missing_measure_rows": max(0, matched_rows - included_rows) if measure else 0,
            "value": value,
        }],
    }


def guide_from_schema(
    question: str,
    files: dict[str, pd.DataFrame],
    pii_columns: dict[str, set[str]] | None = None,
) -> LocalTableAnswer | None:
    """Describe safe, available fields and suggest grounded query shapes."""
    if not files:
        return None
    tokens = _tokens(question)
    ranked: list[tuple[int, str, pd.DataFrame]] = []
    for filename, frame in files.items():
        score = len(_tokens(filename) & tokens)
        for column in frame.columns:
            score += len(_tokens(str(column)) & tokens)
        ranked.append((score, filename, frame))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        names = ", ".join(filename for _, filename, _ in ranked[:6])
        text = (
            f"وجدت عدة ملفات أو أوراق متقاربة الصلة ({names}). حدّد اسم الملف أو الورقة حتى لا أخلط البيانات."
            if _language_is_arabic(question) else
            f"I found several equally relevant files or sheets ({names}). Name one source so I don't mix datasets."
        )
        return LocalTableAnswer(text, "", "clarify", "", 0, [], [], priority=True)

    _, filename, frame = ranked[0]
    excluded = set((pii_columns or {}).get(filename, set()))
    safe_columns = [
        str(column) for column in frame.columns
        if str(column) not in excluded and _safe_column(column)
        and str(column) not in {"PDF page", "OCR confidence", "PDF extraction method"}
    ]
    numeric = [column for column in safe_columns if _numeric_series(frame[column]) is not None]
    dates = [
        column for column in safe_columns
        if re.search(r"(date|period|month|year|time|تاريخ|فترة|شهر|سنة)", column, re.I)
    ]
    categories = [
        column for column in safe_columns
        if column not in numeric and 1 < frame[column].nunique(dropna=True) <= 50
    ]
    if _language_is_arabic(question):
        answer = (
            f"لم أُجرِ حساباً لأن السؤال لا يحدد عملية وعموداً بوضوح في «{filename}». "
            "يمكنني حساب العدد والإجمالي والمتوسط والأعلى/الأدنى، أو التجميع حسب فئة، "
            "أو عرض اتجاه زمني باستخدام الأعمدة الآمنة المكتشفة."
        )
        detail = (
            f"المصدر: {filename} · الصفوف: {len(frame):,}\n"
            f"الأعمدة الرقمية: {', '.join(numeric[:12]) or 'لا يوجد'}\n"
            f"أعمدة التاريخ/الفترة: {', '.join(dates[:8]) or 'لا يوجد'}\n"
            f"أعمدة الفئات: {', '.join(categories[:12]) or 'لا يوجد'}\n"
            "أمثلة: «كم سجل؟»؛ «إجمالي [اسم العمود الرقمي] حسب [عمود الفئة]»؛ "
            "«كم سجل في [قيمة فئة موجودة]؟»."
        )
    else:
        answer = (
            f"I didn't calculate a metric because the question doesn't identify an operation and column "
            f"unambiguously in “{filename}”. I can count, total, average, find highest/lowest values, "
            "group by a category, or show a time trend using the detected safe columns."
        )
        detail = (
            f"Source: {filename} · rows: {len(frame):,}\n"
            f"Numeric columns: {', '.join(numeric[:12]) or 'none detected'}\n"
            f"Date/period columns: {', '.join(dates[:8]) or 'none detected'}\n"
            f"Category columns: {', '.join(categories[:12]) or 'none detected'}\n"
            "Examples: “How many records?”; “Total [numeric column] by [category column]”; "
            "“How many records have [an observed category value]?”"
        )
    return LocalTableAnswer(
        answer, detail, "schema_guide", filename, len(frame), safe_columns,
        ["No metric was calculated; guidance is based on the uploaded schema."],
    )


def analyze_local_question(
    question: str,
    files: dict[str, pd.DataFrame],
    pii_columns: dict[str, set[str]] | None = None,
) -> LocalTableAnswer | None:
    """Answer natural-language aggregate questions or extractive PDF queries."""
    if not files:
        return None

    q = unicodedata.normalize("NFKC", question).strip()
    q_tokens = _tokens(q)
    raw_tokens = set(_TOKEN.findall(q.lower()))
    arabic = _language_is_arabic(q)
    if not q_tokens:
        return None

    document_terms = {"summarize", "summary", "document", "document says", "text", "اكتب", "لخص", "لخصي", "المستند", "الوثيقة"}
    aggregate_words = {
        "sum", "total", "average", "mean", "count", "how", "many", "highest",
        "lowest", "largest", "smallest", "top", "bottom", "rank", "group",
        "compare", "trend", "sum", "overall", "average", "أعلى", "أقل",
        "متوسط", "مجموع", "إجمالي", "اجمالي", "عدد", "كم", "حسب", "اتجاه",
        "maximum", "minimum", "max", "min", "avg", "breakdown", "distribution",
        "توزيع", "تصنيف", "تقسيم", "الأكثر", "الاكثر", "معدل", "شهري", "سنويا",
    }
    is_document_request = bool(q_tokens & document_terms)
    explanatory_terms = {
        "define", "definition", "meaning", "explain", "means",
        "تعريف", "معنى", "اشرح", "يعني",
    }
    financial_question = bool(
        _semantic_concepts(q) & _FINANCIAL_MEASURE_CONCEPTS
        and not (q_tokens & explanatory_terms)
        and not is_document_request
    )
    has_aggregation_intent = bool(
        (q_tokens & aggregate_words)
        or (raw_tokens & {"by", "per", "each", "group", "grouped", "trend", "حسب", "لكل", "كل"})
        or financial_question
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

    numeric_map = {
        str(column): _numeric_series(frame[column])
        for column in safe_columns
    }
    numeric_columns = [column for column, series in numeric_map.items() if series is not None]
    category_filters, ambiguous_filters = _natural_category_filters(q, frame, safe_columns)
    if ambiguous_filters:
        choices = "; ".join(f"{column}: {', '.join(values[:6])}" for column, values in ambiguous_filters[:5])
        return LocalTableAnswer(
            _localized(
                q,
                "The request matches multiple observed category values. Name the exact value(s) so I don't apply the wrong filter.",
                "يطابق السؤال عدة قيم فئوية موجودة. حدّد القيمة المطلوبة بدقة لتجنب تطبيق مرشح غير صحيح.",
            ),
            f"Possible values: {choices}", "clarify", filename, len(frame), safe_columns, [], priority=True,
        )

    record_question = bool(q_tokens & _RECORD_TERMS)
    possible_numeric_measures = _match_columns(q, frame, numeric_columns)
    arabic_sum_intent = bool(
        "كم" in q_tokens and possible_numeric_measures
        and (bool(q_tokens & _SUM_TERMS) or not record_question)
    )
    count_intent = bool(q_tokens & (_COUNT_TERMS - {"كم"})) or (
        "كم" in q_tokens and not arabic_sum_intent
    )
    if record_question and category_filters and not count_intent:
        count_intent = True
        has_aggregation_intent = True
    if not has_aggregation_intent:
        return None

    hard_filter_terms = re.compile(
        r"\b(excluding|exclude|except|greater than|less than|above|below|between|after|before|since|until|during|versus|vs|join|ratio|median|percentile)\b"
        r"|باستثناء|بعد|قبل|بين",
        re.I,
    )
    if hard_filter_terms.search(q):
        return LocalTableAnswer(
            _localized(
                q,
                "I couldn't safely interpret this condition or operation; I won't report a partial or unfiltered result. " + HELP,
                "تعذر تفسير هذا الشرط أو العملية بأمان؛ لن أعرض نتيجة جزئية أو غير مصفاة. " + HELP,
            ),
            "", "clarify", filename, len(frame), safe_columns, [], priority=True,
        )
    explicit_filter_request = bool(re.search(r"\b(where|only|for|in|with)\b|فقط|في|لدى", q, re.I))
    grouping_request = bool(re.search(r"\b(by|per|each|group|grouped)\b|حسب|لكل|كل", q, re.I))
    source_clause = re.search(r"\b(?:in|from)\s+([^\s,?.]+)", q, re.I)
    source_selected = bool(
        source_clause
        and _tokens(source_clause.group(1)) & _tokens(filename)
        and (
            re.search(r"\.(?:csv|xlsx?|jsonl?|pdf|parquet)$", source_clause.group(1), re.I)
            or "$." in filename
            or " — " in filename
        )
        and not category_filters
    )
    explicit_filter_request = explicit_filter_request and not source_selected
    if explicit_filter_request and not category_filters and not grouping_request:
        categories = [
            column for column in safe_columns
            if column not in numeric_columns and frame[column].nunique(dropna=True) <= 50
        ]
        return LocalTableAnswer(
            _localized(
                q,
                "I couldn't match the requested filter to one exact value in the uploaded data. I won't return an unfiltered result.",
                "لم أجد قيمة مطابقة تماماً للمرشح في البيانات؛ لن أعرض نتيجة غير مصفاة.",
            ),
            _localized(
                q,
                f"Available category columns: {', '.join(categories[:10]) or 'none detected'}",
                f"أعمدة الفئات المتاحة: {', '.join(categories[:10]) or 'لم تُكتشف'}",
            ),
            "clarify", filename, len(frame), safe_columns, [], priority=True,
        )
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d+(?:\.\d+)?\b", q):
        return LocalTableAnswer(
            _localized(
                q,
                "The question includes a date or numeric condition that needs an explicit, unambiguous filter. Use the displayed column name and ISO dates (YYYY-MM-DD), or describe an exact observed category.",
                "يتضمن السؤال شرطاً رقمياً أو تاريخياً يحتاج إلى مرشح صريح وواضح. استخدم اسم العمود الظاهر وتاريخ YYYY-MM-DD، أو اذكر قيمة فئوية موجودة حرفياً.",
            ),
            HELP, "clarify", filename, len(frame), safe_columns, [], priority=True,
        )

    filtered_frame = frame
    filter_missing_rows = 0
    filter_audit: list[dict[str, Any]] = []
    if category_filters:
        mask = pd.Series(True, index=frame.index)
        missing_mask = pd.Series(False, index=frame.index)
        for column, operator, value in category_filters:
            present = frame[column].notna()
            missing_mask |= ~present
            matches = frame[column].eq(value) if operator == "=" else frame[column].ne(value)
            mask &= present & matches.fillna(False)
            filter_audit.append({
                "column": column, "operator": operator, "value": value, "kind": "category",
            })
        filter_missing_rows = int(missing_mask.sum())
        filtered_frame = frame.loc[mask]
    if not numeric_columns and not count_intent:
        return LocalTableAnswer(
            _localized(
                q,
                "This file has no columns with enough consistently numeric values for a reliable calculation. Check the extracted columns and number formats.",
                "لا يحتوي الملف على عمود رقمي متسق بما يكفي لإجراء حساب موثوق. راجع الأعمدة المستخرجة وتنسيق الأرقام.",
            ),
            "", "clarify", filename, len(frame), safe_columns, [],
        )

    average_intent = bool(q_tokens & _AVERAGE_TERMS)
    top_intent = bool(q_tokens & _TOP_TERMS)
    bottom_intent = bool(q_tokens & _BOTTOM_TERMS)
    trend_intent = bool(q_tokens & _TREND_TERMS)
    sum_intent = (
        bool(q_tokens & _SUM_TERMS)
        or bool(raw_tokens & {"how", "much"})
        or arabic_sum_intent
        or (
            financial_question
            and not any((count_intent, average_intent, top_intent, bottom_intent, trend_intent))
        )
    )
    by_intent = (
        bool(q_tokens & (_GROUP_TERMS - {"by", "per", "each"}))
        or bool(raw_tokens & {"by", "per", "each", "حسب", "لكل", "كل"})
        or trend_intent
    )

    if not any((count_intent, average_intent, sum_intent, top_intent, bottom_intent, trend_intent)):
        if by_intent and _match_columns(q, frame, numeric_columns):
            sum_intent = True
        else:
            return None

    matched_numeric = _match_columns(q, frame, numeric_columns)
    generic_measure_fallback = bool(
        len(matched_numeric) == 1
        and _semantic_concepts(matched_numeric[0]) & {"amount"}
        and _semantic_concepts(q) & _FINANCIAL_MEASURE_CONCEPTS
    )
    if len(matched_numeric) > 1:
        return LocalTableAnswer(
            _localized(
                q,
                "The question could refer to more than one numeric column. Name the exact measure (for example, \"total Net Sales\").",
                "قد يشير السؤال إلى أكثر من عمود رقمي. حدّد المقياس المطلوب باسمه بدقة.",
            ),
            _localized(
                q,
                f"Possible measures: {', '.join(matched_numeric[:10])}",
                f"المقاييس المحتملة: {', '.join(matched_numeric[:10])}",
            ),
            "clarify", filename, len(frame), safe_columns, [], priority=True,
        )
    if not matched_numeric and not count_intent:
        return LocalTableAnswer(
            _localized(
                q,
                f"Please name the measure to calculate. Numeric columns: {', '.join(numeric_columns[:10])}",
                f"حدّد المقياس المطلوب حسابه. الأعمدة الرقمية: {', '.join(numeric_columns[:10])}",
            ),
            "", "clarify", filename, len(frame), safe_columns, [],
        )

    measure = None if count_intent else (matched_numeric[0] if matched_numeric else None)
    numeric_warnings = []
    if measure is not None:
        excluded_rows = len(frame) - int(numeric_map[measure].notna().sum())
        if excluded_rows:
            numeric_warnings.append(f"{excluded_rows:,} row(s) with missing or non-numeric {measure} were excluded.")
    if generic_measure_fallback and measure is not None:
        numeric_warnings.append(_localized(
            q,
            f"Only one eligible numeric column ({measure}) was available, so it was used as the requested financial measure. Confirm this mapping before acting.",
            f"لم يتوفر سوى عمود رقمي واحد ({measure})، لذا استُخدم للمقياس المالي المطلوب. تحقّق من هذا الربط قبل اتخاذ إجراء.",
        ))
    dimension_candidates = [
        column for column in safe_columns
        if column not in numeric_columns and column not in (pii_columns or {}).get(filename, set())
        and frame[column].nunique(dropna=True) > 1
        and frame[column].nunique(dropna=True) <= min(50, max(2, int(len(frame) ** 0.5) + 1))
    ]
    dimensions = _match_columns(q, frame, dimension_candidates) if by_intent else []
    if len(dimensions) > 1:
        return LocalTableAnswer(
            _localized(
                q,
                "Please name one grouping column; the question matches more than one.",
                "حدّد عمود تجميع واحداً؛ فالسؤال يطابق أكثر من عمود.",
            ),
            _localized(
                q,
                f"Possible groupings: {', '.join(dimensions[:10])}",
                f"أعمدة التجميع المحتملة: {', '.join(dimensions[:10])}",
            ),
            "clarify", filename, len(frame), safe_columns, [],
        )
    dimension = dimensions[0] if dimensions else None

    if by_intent and dimension is None and not trend_intent:
        return LocalTableAnswer(
            _localized(
                q,
                "I couldn't identify one unambiguous group-by column. Include its column name, such as \"by department\".",
                "تعذر تحديد عمود تجميع واحد بوضوح. اذكر اسم العمود المطلوب.",
            ),
            _localized(
                q,
                f"Available groupings: {', '.join(dimension_candidates[:10])}",
                f"أعمدة التجميع المتاحة: {', '.join(dimension_candidates[:10])}",
            ),
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
        date_strings = filtered_frame[date_column].dropna().astype(str)
        ambiguous = date_strings.str.extract(r"^(\d{1,2})[/-](\d{1,2})[/-]\d{2,4}$").dropna()
        if not ambiguous.empty:
            numbers = ambiguous.astype(int)
            if ((numbers[0] <= 12) & (numbers[1] <= 12) & (numbers[0] != numbers[1])).any():
                return LocalTableAnswer(
                    f"The {date_column} column has ambiguous day/month dates. Convert it to YYYY-MM-DD before requesting a trend.",
                    "", "clarify", filename, len(frame), safe_columns, [], priority=True,
                )
        dates = pd.to_datetime(filtered_frame[date_column], errors="coerce", dayfirst=False)
        valid = dates.notna()
        if not valid.any():
            return LocalTableAnswer(
                f"The {date_column} column contains no reliably parseable dates.",
                "", "clarify", filename, len(frame), safe_columns, [],
            )
        series = numeric_map[measure].loc[filtered_frame.index] if measure else None
        if series is None:
            return None
        valid = valid & series.notna()
        monthly = pd.DataFrame({"period": dates[valid].dt.to_period("M").astype(str), "value": series[valid]})
        grouped = monthly.groupby("period", sort=True)["value"].sum(min_count=1).dropna()
        detail = "\n".join(f"{period}: {value:,.2f}" for period, value in grouped.tail(12).items())
        audit = _build_filter_audit(
            filename, "trend", measure, frame, filtered_frame, filter_audit,
            filter_missing_rows, int(valid.sum()),
            value=float(series[valid].sum()) if filter_audit and not series[valid].empty else None,
        ) if filter_audit else None
        return LocalTableAnswer(
            (
                f"الإجمالي الشهري لـ {measure} من {filename} استناداً إلى {int(valid.sum())} صفاً بتواريخ صالحة. "
                "يُعرض أحدث 12 فترة فقط."
                if arabic else
                f"Monthly total of {measure} from {filename} based on {int(valid.sum())} rows with valid dates. Only the 12 most recent periods are shown."
            ),
            detail, "trend", filename, int(valid.sum()), safe_columns, numeric_warnings,
            query_audit=audit,
        )

    if count_intent and measure is None:
        if dimension is None:
            count = len(filtered_frame)
            audit = _build_filter_audit(
                filename, "count", None, frame, filtered_frame, filter_audit,
                filter_missing_rows, count, count,
            ) if filter_audit else None
            return LocalTableAnswer(
                (
                    f"عدد السجلات في {filename}: {count:,} صف."
                    if arabic else f"Record count in {filename}: {count:,} rows."
                ),
                (
                    f"{count:,} صف · {len(safe_columns)} أعمدة غير حساسة"
                    if arabic else f"{count:,} rows · {len(safe_columns)} non-sensitive columns"
                ),
                "count", filename, count, safe_columns, [], query_audit=audit,
            )
        counts = filtered_frame.groupby(dimension, dropna=True).size().sort_values(ascending=False).head(12)
        detail = "\n".join(f"{key}: {int(value):,} rows" for key, value in counts.items())
        audit = _build_filter_audit(
            filename, "count_by", None, frame, filtered_frame, filter_audit,
            filter_missing_rows, len(filtered_frame),
        ) if filter_audit else None
        return LocalTableAnswer(
            (
                f"عدد السجلات حسب {dimension} في {filename}. يُعرض ما يصل إلى 12 مجموعة."
                if arabic else f"Record counts grouped by {dimension} in {filename}. Showing up to 12 groups."
            ),
            (
                "\n".join(f"{key}: {int(value):,} صف" for key, value in counts.items())
                if arabic else detail
            ),
            "count_by", filename, len(filtered_frame), safe_columns, [],
            query_audit=audit,
        )

    values = numeric_map[measure].loc[filtered_frame.index]
    if dimension:
        reduced = pd.DataFrame({"group": filtered_frame[dimension], "value": values})
        aggregation = "mean" if average_intent else "sum"
        groups = reduced.groupby("group", dropna=True)["value"]
        grouped = (groups.mean() if aggregation == "mean" else groups.sum(min_count=1)).dropna()
        grouped = grouped.sort_values(ascending=not (top_intent or bottom_intent)) if not (top_intent or bottom_intent) else grouped.sort_values(ascending=bottom_intent)
        grouped = grouped.head(12)
        detail = "\n".join(f"{key}: {value:,.2f}" for key, value in grouped.items())
        audit = _build_filter_audit(
            filename, "grouped_average" if average_intent else "grouped_total",
            measure, frame, filtered_frame, filter_audit, filter_missing_rows,
            int(values.notna().sum()),
        ) if filter_audit else None
        return LocalTableAnswer(
            (
                f"{'متوسط' if average_intent else 'إجمالي'} {measure} حسب {dimension} في {filename}. "
                "يُعرض ما يصل إلى 12 مجموعة."
                if arabic else
                f"{'Average' if average_intent else 'Total'} {measure} grouped by {dimension} in {filename}. Showing up to 12 groups."
            ),
            detail, "grouped_average" if average_intent else "grouped_total",
            filename, int(values.notna().sum()), safe_columns, numeric_warnings,
            query_audit=audit,
        )

    if top_intent or bottom_intent:
        value = values.max() if top_intent else values.min()
        operation = "maximum" if top_intent else "minimum"
    elif average_intent:
        value, operation = values.mean(), "average"
    else:
        value, operation = values.sum(), "total"

    labels = (
        {"maximum": "القيمة الأعلى", "minimum": "القيمة الأدنى", "average": "المتوسط", "total": "الإجمالي"}
        if arabic else
        {"maximum": "Maximum", "minimum": "Minimum", "average": "Average", "total": "Total"}
    )
    audit = _build_filter_audit(
        filename, operation, measure, frame, filtered_frame, filter_audit,
        filter_missing_rows, int(values.notna().sum()),
        value=float(value) if pd.notna(value) else None,
    ) if filter_audit else None
    return LocalTableAnswer(
        (
            f"{labels[operation]} لـ {measure} في {filename} استناداً إلى {int(values.notna().sum())} قيمة رقمية."
            if arabic else
            f"{labels[operation]} {measure} in {filename} from {int(values.notna().sum())} numeric records."
        ),
        f"{labels[operation]} {measure}: {value:,.2f}",
        operation, filename, int(values.notna().sum()), safe_columns, numeric_warnings,
        query_audit=audit,
    )
