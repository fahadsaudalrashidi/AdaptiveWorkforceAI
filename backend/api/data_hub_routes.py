"""Authenticated, request-scoped data hub endpoints.

The hub accepts tabular uploads for profiling, trend projections, and summary
exports. Uploaded bytes stay in memory for the request and are not persisted.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.data_hub_engine import (
    CLEANING_OPTIONS,
    MAX_FILES_PER_REQUEST,
    MAX_FILE_BYTES,
    MAX_REQUEST_BYTES,
    SUPPORTED_DATA_HUB_EXTENSIONS,
    build_summary_pdf,
    build_summary_xlsx,
    forecast_frame,
    profile_upload,
)
from backend.core.excel_ingestion_engine import ExcelIngestionEngine
from backend.core.security_middleware import require_permission

logger = logging.getLogger(__name__)


def create_data_hub_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/local/data-hub",
        tags=["Interactive Data Hub"],
        dependencies=[Depends(require_permission("run_analysis"))],
    )

    def parse_cleaning_options(value: str) -> list[str]:
        try:
            options = json.loads(value or "[]")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="cleaning_options must be a JSON array.") from exc
        if not isinstance(options, list) or any(not isinstance(item, str) for item in options):
            raise HTTPException(status_code=422, detail="cleaning_options must be a JSON array of option names.")
        unknown = set(options) - CLEANING_OPTIONS
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unsupported cleaning option(s): {', '.join(sorted(unknown))}.")
        return list(dict.fromkeys(options))

    async def read_uploads(files: list[UploadFile]) -> list[tuple[str, bytes]]:
        if not files:
            raise HTTPException(status_code=422, detail="Upload at least one CSV, Excel, or JSON file.")
        if len(files) > MAX_FILES_PER_REQUEST:
            raise HTTPException(status_code=413, detail=f"Upload no more than {MAX_FILES_PER_REQUEST} files at a time.")
        total = 0
        seen_names: set[str] = set()
        uploads: list[tuple[str, bytes]] = []
        for file in files:
            filename = Path(file.filename or "upload.dat").name
            normalized_name = filename.casefold()
            if normalized_name in seen_names:
                raise HTTPException(status_code=422, detail="Each uploaded file must have a unique filename.")
            seen_names.add(normalized_name)
            suffix = Path(filename).suffix.lower()
            if suffix not in SUPPORTED_DATA_HUB_EXTENSIONS:
                raise HTTPException(status_code=415, detail=f"{filename}: use CSV, XLS, XLSX, or JSON.")
            content = await file.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise HTTPException(status_code=413, detail=f"{filename}: each file must be 25 MB or smaller.")
            total += len(content)
            if total > MAX_REQUEST_BYTES:
                raise HTTPException(status_code=413, detail="The combined upload limit is 50 MB.")
            uploads.append((filename, content))
        return uploads

    async def inspect_uploads(
        uploads: list[tuple[str, bytes]],
        options: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        datasets: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for filename, content in uploads:
            try:
                profiles = await asyncio.to_thread(profile_upload, content, filename, options)
                datasets.extend(profiles)
            except ValueError:
                logger.info("Data Hub rejected an unreadable upload: %s", filename)
                errors.append({"filename": filename, "detail": "The file could not be profiled safely. Verify it is a valid table and try again."})
            except Exception:
                logger.exception("Data Hub profiling failed for %s", filename)
                errors.append({"filename": filename, "detail": "The file could not be profiled safely. Check its format and try again."})
        return datasets, errors

    @router.post("/inspect")
    async def inspect_data(
        files: list[UploadFile] = File(...),
        cleaning_options: str = Form("[]"),
    ) -> dict[str, Any]:
        """Inspect uploaded tables and return only schema/aggregate metadata."""
        options = parse_cleaning_options(cleaning_options)
        uploads = await read_uploads(files)
        datasets, errors = await inspect_uploads(uploads, options)
        if not datasets:
            detail = "; ".join(f"{item['filename']}: {item['detail']}" for item in errors)
            raise HTTPException(status_code=422, detail=detail or "No readable tables were found.")
        return {
            "datasets": datasets,
            "errors": errors,
            "files_processed": len({item["filename"] for item in datasets}),
            "privacy": {
                "mode": "request_scoped_local_processing",
                "persisted": False,
                "source_rows_returned": False,
                "sensitive_column_values_returned": False,
            },
        }

    @router.post("/forecast")
    async def forecast_data(
        file: UploadFile = File(...),
        sheet: str = Form(""),
        date_column: str = Form(...),
        metric_column: str = Form("__rows__"),
        aggregation: str = Form("count"),
        horizon: int = Form(3),
        language: str = Form("en"),
    ) -> dict[str, Any]:
        """Project a monthly trend from a selected date and measure."""
        filename = Path(file.filename or "upload.dat").name
        if Path(filename).suffix.lower() not in SUPPORTED_DATA_HUB_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Use CSV, XLS, XLSX, or JSON.")
        raw = await file.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="Each file must be 25 MB or smaller.")
        if not raw:
            raise HTTPException(status_code=422, detail="The uploaded file is empty.")
        if language not in {"en", "ar"}:
            raise HTTPException(status_code=422, detail="language must be 'en' or 'ar'.")

        def build() -> dict[str, Any]:
            results = ExcelIngestionEngine().ingest_all(raw, filename)
            selected = next(
                (
                    result for name, result in results
                    if result.success and result.df is not None and (not sheet or name == sheet)
                ),
                None,
            )
            if selected is None or selected.df is None:
                raise ValueError("The selected worksheet could not be found or read.")
            result = forecast_frame(
                selected.df,
                filename=filename,
                sheet=selected.sheet_used or sheet or "Data",
                date_column=date_column,
                metric_column=metric_column,
                aggregation=aggregation,
                horizon=horizon,
            )
            if language == "ar":
                model_names = {
                    "naive": "الساذج",
                    "linear_trend": "الاتجاه الخطي",
                    "seasonal_naive": "الموسمي الساذج",
                }
                result["method"] = (
                    f"اختيار النموذج بالتحقق التتابعي "
                    f"({model_names.get(result['selected_model'], result['selected_model'])}) "
                    "مع حدود خطأ تتسع مع الأفق"
                )
                result["limitations"] = [
                    "يُختار النموذج باستخدام اختبار تتابعي قصير لفترة واحدة؛ وقد يكون الاختيار غير مستقر مع قلة البيانات التاريخية.",
                    "النطاقات حدود تقريبية مبنية على أخطاء الاختبار وبحد أدنى غير صفري، وليست ضمانات أو احتمالات معايرة.",
                    "لا تتضمن النماذج العوامل السببية أو القيود التشغيلية أو تغييرات السياسات المستقبلية.",
                    "تحقق من النتائج وفقاً للمعرفة التشغيلية قبل استخدامها في قرارات القوى العاملة أو المالية.",
                ]
            return result

        try:
            return await asyncio.to_thread(build)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            logger.exception("Data Hub trend projection failed for %s", filename)
            raise HTTPException(status_code=422, detail="The selected data could not produce a valid monthly trend.")

    async def export_profiles(
        files: list[UploadFile],
        cleaning_options: str,
    ) -> list[dict[str, Any]]:
        options = parse_cleaning_options(cleaning_options)
        uploads = await read_uploads(files)
        datasets, errors = await inspect_uploads(uploads, options)
        if errors:
            detail = "; ".join(f"{item['filename']}: {item['detail']}" for item in errors)
            raise HTTPException(status_code=422, detail=detail)
        if not datasets:
            raise HTTPException(status_code=422, detail="No readable tables were found.")
        return datasets

    @router.post("/export.xlsx")
    async def export_summary_xlsx(
        files: list[UploadFile] = File(...),
        cleaning_options: str = Form("[]"),
    ) -> Response:
        """Download a workbook of schema and aggregate findings—never raw rows."""
        profiles = await export_profiles(files, cleaning_options)
        try:
            content = await asyncio.to_thread(build_summary_xlsx, profiles)
        except Exception:
            logger.exception("Data Hub workbook export failed")
            raise HTTPException(status_code=500, detail="The summary workbook could not be generated.")
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="thrive-data-summary.xlsx"'},
        )

    @router.post("/export.pdf")
    async def export_summary_pdf(
        files: list[UploadFile] = File(...),
        cleaning_options: str = Form("[]"),
        language: str = Form("en"),
    ) -> Response:
        """Create a bilingual-font PDF containing profile summaries only."""
        if language not in {"en", "ar"}:
            raise HTTPException(status_code=422, detail="language must be 'en' or 'ar'.")
        profiles = await export_profiles(files, cleaning_options)
        try:
            content = await asyncio.to_thread(build_summary_pdf, profiles, language)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception:
            logger.exception("Data Hub PDF export failed")
            raise HTTPException(status_code=500, detail="The summary PDF could not be generated.")
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="thrive-data-summary.pdf"'},
        )

    return router
