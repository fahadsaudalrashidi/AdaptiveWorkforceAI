"""Validate explicitly reviewed rows without marking original OCR as verified.

The original PDF is re-uploaded and hashed on each request. Nothing here
persists documents, trusts a browser-provided OCR flag, or executes formulas.
"""
from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd


def reviewed_tables_from_json(
    raw: str, sources: dict[str, dict[str, Any]],
) -> list[tuple[str, pd.DataFrame, dict[str, Any]]]:
    if not raw:
        return []
    if len(raw.encode("utf-8")) > 1_000_000:
        raise ValueError("Reviewed tables exceed the 1 MB limit.")
    try:
        tables = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("Reviewed tables must be valid JSON.") from exc
    if not isinstance(tables, list) or not 1 <= len(tables) <= 10:
        raise ValueError("Submit between one and ten reviewed tables.")
    reviewed = []
    seen = set()
    for table in tables:
        if not isinstance(table, dict):
            raise ValueError("Each reviewed table must be an object.")
        source_id = table.get("source_id")
        source = sources.get(source_id) if isinstance(source_id, str) else None
        if not source or not source.get("eligible"):
            raise ValueError("Re-upload the matching PDF. Its extraction must pass governance before review.")
        if source_id in seen:
            raise ValueError("Only one reviewed table per source PDF is accepted per request.")
        seen.add(source_id)
        if table.get("confirmed_headers") is not True or table.get("scope") != "reviewed_rows_only":
            raise ValueError("Confirm the column headings and the reviewed-rows-only scope.")
        columns = table.get("columns")
        if not isinstance(columns, list) or not 1 <= len(columns) <= 30:
            raise ValueError("A reviewed table needs 1–30 column headings.")
        if any(not isinstance(c, str) or not c.strip() or len(c) > 100 for c in columns):
            raise ValueError("Every column heading must be non-empty and at most 100 characters.")
        columns = [c.strip() for c in columns]
        if len({c.casefold() for c in columns}) != len(columns):
            raise ValueError("Reviewed column headings must be unique.")
        rows = table.get("rows")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
            raise ValueError("A reviewed table needs 1–1,000 rows.")
        values, pages = [], []
        for row in rows:
            if not isinstance(row, dict) or row.get("verified") is not True:
                raise ValueError("Verify every included row against its source page.")
            page = row.get("page")
            if type(page) is not int or page not in source["pages"]:
                raise ValueError("Each reviewed row must refer to an extracted page in the matching PDF.")
            cells = row.get("values")
            if not isinstance(cells, list) or len(cells) != len(columns):
                raise ValueError("Every reviewed row must have one cell for each column.")
            for cell in cells:
                if type(cell) not in (str, int, float) or len(str(cell)) > 500:
                    raise ValueError("Reviewed cells must be text or numbers of at most 500 characters.")
                if isinstance(cell, float) and not math.isfinite(cell):
                    raise ValueError("Reviewed numeric values must be finite.")
            if not any(str(cell).strip() for cell in cells):
                raise ValueError("Remove empty rows before confirming the table.")
            values.append(cells)
            pages.append(page)
        metadata = {
            "source_id": source_id,
            "source_filename": source["filename"],
            "scope": "reviewed_rows_only",
            "row_pages": pages,
            "rows_confirmed": len(rows),
            "original_ocr_remains_unverified": True,
        }
        frame = pd.DataFrame(values, columns=columns)
        frame.attrs["verified_ocr_review"] = metadata
        reviewed.append((f"{source['filename']} — User-reviewed rows", frame, metadata))
    return reviewed
