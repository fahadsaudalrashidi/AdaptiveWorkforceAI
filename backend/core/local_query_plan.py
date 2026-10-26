"""Bounded local query grammar. No generated code, SQL, or expression evaluation."""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Callable, Literal

import pandas as pd


Operator = Literal["=", "!=", ">", ">=", "<", "<="]
Aggregation = Literal["total", "average", "count"]
ValueKind = Literal["category", "date", "number"]


@dataclass(frozen=True)
class RowFilter:
    column: str
    operator: Operator
    value: str | float
    kind: ValueKind


@dataclass(frozen=True)
class QueryPlan:
    source_file: str
    operation: Aggregation
    measure: str | None
    cohorts: tuple[tuple[RowFilter, ...], ...]


@dataclass(frozen=True)
class CohortEvidence:
    filters: tuple[RowFilter, ...]
    source_rows: int
    matched_rows: int
    included_rows: int
    excluded_rows: int
    missing_filter_rows: int
    missing_measure_rows: int
    value: float | int | None

    def to_dict(self) -> dict:
        return asdict(self)


class PlanError(ValueError):
    """A clarification, never a reason to fall back to an unfiltered query."""


HELP = (
    'Use exact column names: total "Sales" where "Region" = "West" and '
    '"Date" >= "2025-01-01". For comparisons: compare total "Sales" where '
    '"Region" = "West" versus "Region" = "East". With multiple sources, add '
    'from "exact-file.csv" before where. Supported operations: total, average, '
    'count records; filters: =, !=, >, >=, <, <= joined by and. '
    'Quote category/date values; dates must be YYYY-MM-DD. No joins or formulas.'
)
_HEADER = re.compile(
    r'(?P<compare>compare\s+)?(?P<op>total|sum|average|mean|count)\s+'
    r'(?P<measure>"[^"]+"|[^"]+?)'
    r'(?:\s+from\s+"(?P<source>[^"]+)")?\s+where\s+(?P<body>.+)',
    re.I | re.S,
)
# Consume the entire input using a tiny lexer; quoted text is always data.
_LEX = re.compile(r'\s*("[^"]*"|>=|<=|!=|=|>|<|[^\s"=<>!]+)')
_NUMBER = re.compile(r"-?(?:\d+(?:\.\d+)?|\.\d+)")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MAX_EXACT_INTEGER = 2**53 - 1
_CURRENCY_CODES = frozenset({"USD", "EUR", "GBP", "SAR", "AED", "CAD", "AUD", "JPY", "KWD", "BHD", "QAR", "OMR"})
_CURRENCY = re.compile(r"(?<![A-Za-z])(?:" + "|".join(sorted(_CURRENCY_CODES)) + r")(?![A-Za-z])|[$€£﷼]", re.I)


def _lex(text: str) -> list[str]:
    tokens, pos = [], 0
    while pos < len(text):
        match = _LEX.match(text, pos)
        if not match:
            raise PlanError("Unsupported filter syntax. " + HELP)
        tokens.append(match[1])
        pos = match.end()
    return tokens


def _column(name: str, columns: list[str], blocked: set[str]) -> str:
    name = name.strip().strip('"')
    matches = [c for c in columns if c.casefold() == name.casefold()]
    if len(matches) != 1:
        raise PlanError("Name one exact, unambiguous column; partial column names are not supported.")
    if matches[0] in blocked:
        raise PlanError("I can't filter, compare, or calculate using a detected personal-data column.")
    return matches[0]


def _date_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        if getattr(series.dt, "tz", None) is not None:
            raise PlanError("Timezone-aware dates need an explicit timezone interpretation; use verified YYYY-MM-DD dates.")
        return series
    nonmissing = series.dropna().astype(str)
    if not nonmissing.map(lambda s: bool(_ISO_DATE.fullmatch(s))).all():
        raise PlanError("Date filters require unambiguous YYYY-MM-DD source dates; day/month or mixed date formats need clarification.")
    dates = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")
    if (series.notna() & dates.isna()).any():
        raise PlanError("The date column contains invalid dates. Correct them before filtering.")
    return dates


def _numbers(series: pd.Series, column: str) -> pd.Series:
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_complex_dtype(series):
        raise PlanError("Boolean or complex values are not supported numeric measures or thresholds.")
    if pd.api.types.is_numeric_dtype(series):
        values = pd.to_numeric(series, errors="coerce")
    else:
        cleaned = series.astype("string").map(
            lambda s: unicodedata.normalize("NFKC", s).translate(
                str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")
            ) if isinstance(s, str) else s
        ).astype("string").str.strip()
        if cleaned.str.contains(r"[,٬%]", na=False).any():
            raise PlanError("Comma-formatted numbers or percentages need clarification. Use plain decimal numbers without thousands separators or percent symbols.")
        cleaned = cleaned.str.replace(_CURRENCY, "", regex=True).str.strip()
        cleaned = cleaned.str.replace(r"^\((\d+(?:\.\d+)?)\)$", r"-\1", regex=True)
        if not cleaned.dropna().str.fullmatch(_NUMBER).all():
            raise PlanError(f'Column "{column}" is not consistently numeric. Use verified plain decimal values.')
        values = pd.to_numeric(cleaned, errors="coerce")
    if (series.notna() & values.isna()).any() or not values.dropna().map(math.isfinite).all():
        raise PlanError(f'Column "{column}" has invalid or non-finite numbers; correct them before calculating.')
    if values.dropna().map(lambda v: abs(v) > _MAX_EXACT_INTEGER).any():
        raise PlanError("Values exceed the safely supported numeric magnitude (2^53 - 1).")
    return values


def _currency(frame: pd.DataFrame, columns: set[str]) -> str | None:
    currencies: set[str] = set()
    aliases = {"€": "EUR", "£": "GBP", "﷼": "SAR"}
    for column in columns:
        for value in [column, *frame[column].dropna().astype(str).tolist()]:
            for token in _CURRENCY.findall(value):
                if token == "$":
                    raise PlanError("The $ symbol is currency-ambiguous. Use an explicit currency code and verified numeric values.")
                currencies.add(aliases.get(token, token.upper()))
    for column in frame.columns:
        if re.fullmatch(r"currency(?: code)?", str(column), re.I):
            present = frame[column].dropna().astype(str).str.upper()
            if frame[column].isna().any() or not present.isin(_CURRENCY_CODES).all():
                raise PlanError("Currency values are missing or ambiguous; separate and verify currencies before calculating.")
            currencies.update(present.unique())
    if len(currencies) > 1:
        raise PlanError("Multiple currencies are present. Separate currencies into a verified single-currency source; no conversion is inferred.")
    return next(iter(currencies), None)


def parse_plan(question: str, files: dict[str, pd.DataFrame], blocked_columns: Callable) -> QueryPlan:
    match = _HEADER.fullmatch(question)
    if not match:
        raise PlanError("I couldn't safely interpret the entire filtered/comparative request. " + HELP)
    source = match["source"]
    if source is None:
        if len(files) != 1:
            raise PlanError("Multiple files/sheets are available. Specify one exact source. " + HELP)
        source = next(iter(files))
    if source not in files:
        raise PlanError("The exact source file/sheet was not found. Use its full displayed name.")
    frame = files[source]
    if not all(isinstance(c, str) for c in frame.columns) or frame.columns.duplicated().any():
        raise PlanError("Source columns need unique text names before querying.")
    columns = list(frame.columns)
    blocked = blocked_columns(source, columns)
    if any(c in blocked and re.fullmatch(r"currency(?: code)?", c, re.I) for c in columns):
        raise PlanError("Currency interpretation requires an excluded personal-data column; use a verified non-sensitive source.")
    op: Aggregation = {"sum": "total", "mean": "average"}.get(match["op"].lower(), match["op"].lower())
    measure = None if op == "count" and match["measure"].lower() == "records" else _column(match["measure"], columns, blocked)
    if op == "count" and measure is not None:
        raise PlanError('For row counts use "count records"; count-column semantics are not supported.')
    tokens = _lex(match["body"])
    cohorts: list[tuple[RowFilter, ...]] = []
    filters: list[RowFilter] = []
    pos = 0
    while pos < len(tokens):
        start = pos
        while pos < len(tokens) and tokens[pos] not in {"=", "!=", ">", ">=", "<", "<="}:
            pos += 1
        if pos == len(tokens) or pos + 1 >= len(tokens):
            raise PlanError("Incomplete filter. " + HELP)
        column = _column(" ".join(tokens[start:pos]), columns, blocked)
        operator = tokens[pos]
        raw = tokens[pos + 1]
        pos += 2
        if raw.startswith('"'):
            value = raw[1:-1]
            is_date = bool(_ISO_DATE.fullmatch(value))
            if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", value):
                raise PlanError("Ambiguous date values are not supported; use YYYY-MM-DD.")
            date_column = bool(re.search(r"date|period|month|time|تاريخ", column, re.I)) or pd.api.types.is_datetime64_any_dtype(frame[column])
            if is_date or date_column:
                if not is_date:
                    raise PlanError("Use YYYY-MM-DD date values; ambiguous dates are not accepted.")
                try:
                    pd.Timestamp(value)
                except ValueError as exc:
                    raise PlanError("Invalid ISO date in filter.") from exc
                kind: ValueKind = "date"
            else:
                kind = "category"
                if operator not in {"=", "!="}:
                    raise PlanError("Categories support only = and !=; numeric thresholds must be unquoted.")
                categories = frame[column].dropna().tolist()
                if not all(isinstance(v, str) for v in categories):
                    raise PlanError("Categorical filters require consistent text values; use unquoted thresholds for numeric columns.")
                if not any(isinstance(v, str) and v == value for v in categories):
                    raise PlanError("Category values must match the source exactly, including case.")
        elif _NUMBER.fullmatch(raw):
            kind, value = "number", float(raw)
            if not math.isfinite(value) or abs(value) > _MAX_EXACT_INTEGER:
                raise PlanError("Numeric thresholds must be finite and within the safely supported magnitude (2^53 - 1).")
        else:
            raise PlanError("Quote exact category and ISO date values. " + HELP)
        filters.append(RowFilter(column, operator, value, kind))
        if len(filters) > 8:
            raise PlanError("Use no more than eight filters per cohort.")
        if pos == len(tokens):
            break
        connector = tokens[pos].lower()
        pos += 1
        if pos == len(tokens):
            raise PlanError("A filter is missing after the connector.")
        if connector == "versus" and match["compare"] and not cohorts:
            cohorts.append(tuple(filters))
            filters = []
        elif connector != "and":
            raise PlanError("Only and filters and one explicit versus comparison are supported. " + HELP)
    cohorts.append(tuple(filters))
    if bool(match["compare"]) != (len(cohorts) == 2) or any(not c for c in cohorts):
        raise PlanError("A comparison requires exactly two explicit filter sets separated by versus.")
    return QueryPlan(source, op, measure, tuple(cohorts))


def execute_plan(plan: QueryPlan, frame: pd.DataFrame) -> tuple[list[CohortEvidence], str | None]:
    """Execute only the typed allowlist, with missing values excluded explicitly."""
    numeric_columns = {f.column for cohort in plan.cohorts for f in cohort if f.kind == "number"}
    if plan.measure:
        numeric_columns.add(plan.measure)
    currency = _currency(frame, numeric_columns) if numeric_columns else None
    numbers = {c: _numbers(frame[c], c) for c in numeric_columns}
    results = []
    for cohort in plan.cohorts:
        mask = pd.Series(True, index=frame.index)
        missing = pd.Series(False, index=frame.index)
        for condition in cohort:
            series = frame[condition.column]
            value = condition.value
            if condition.kind == "date":
                series, value = _date_series(series), pd.Timestamp(value)
            elif condition.kind == "number":
                series = numbers[condition.column]
            present = series.notna()
            missing |= ~present
            op = condition.operator
            if op == "=":
                matches = series.eq(value)
            elif op == "!=":
                matches = series.ne(value)
            elif op == ">":
                matches = series.gt(value)
            elif op == ">=":
                matches = series.ge(value)
            elif op == "<":
                matches = series.lt(value)
            elif op == "<=":
                matches = series.le(value)
            else:
                raise PlanError("Unsupported operator.")
            mask &= present & matches.fillna(False)
        matched = int(mask.sum())
        if plan.measure is None:
            included, value = matched, matched
        else:
            values = numbers[plan.measure][mask].dropna()
            included = len(values)
            total = math.fsum(float(v) for v in values)
            value = None if not included else total / included if plan.operation == "average" else total
            if value is not None and not math.isfinite(value):
                raise PlanError("The result exceeds the supported numeric range.")
            if value is not None and abs(value) > _MAX_EXACT_INTEGER:
                raise PlanError("The result exceeds the safely supported numeric magnitude (2^53 - 1).")
        results.append(CohortEvidence(cohort, len(frame), matched, included, len(frame) - included,
                                      int(missing.sum()), matched - included, value))
    return results, currency
