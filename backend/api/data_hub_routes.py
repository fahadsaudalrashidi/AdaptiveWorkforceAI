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
    apply_cleaning,
    build_summary_pdf,
    build_summary_xlsx,
    forecast_frame,
    profile_upload,
    workforce_scenario_frame,
    workforce_skills_frame,
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

    def parse_scenarios(value: str) -> list[dict[str, Any]]:
        try:
            scenarios = json.loads(value or "[]")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="scenarios must be a JSON array.") from exc
        if not isinstance(scenarios, list) or any(not isinstance(item, dict) for item in scenarios):
            raise HTTPException(status_code=422, detail="scenarios must be a JSON array of scenario objects.")
        if not 1 <= len(scenarios) <= 3:
            raise HTTPException(status_code=422, detail="Provide one to three scenarios.")
        return scenarios

    async def read_uploads(files: list[UploadFile]) -> list[tuple[str, bytes]]:
        if not files:
            raise HTTPException(status_code=422, detail="Upload at least one CSV, Excel, JSON, or JSON Lines file.")
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
                raise HTTPException(status_code=415, detail=f"{filename}: use CSV, XLS, XLSX, JSON, or JSON Lines.")
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
            raise HTTPException(status_code=415, detail="Use CSV, XLS, XLSX, JSON, or JSON Lines.")
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

    @router.post("/scenario")
    async def scenario_data(
        file: UploadFile = File(...),
        sheet: str = Form(""),
        department_column: str = Form(...),
        headcount_column: str = Form("__rows__"),
        payroll_column: str = Form(...),
        overtime_column: str = Form(""),
        cleaning_options: str = Form("[]"),
        scenarios: str = Form(...),
        language: str = Form("en"),
    ) -> dict[str, Any]:
        """Compare local, assumption-driven workforce scenarios; return aggregates only."""
        filename = Path(file.filename or "upload.dat").name
        if Path(filename).suffix.lower() not in SUPPORTED_DATA_HUB_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Use CSV, XLS, XLSX, JSON, or JSON Lines.")
        raw = await file.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="Each file must be 25 MB or smaller.")
        if not raw:
            raise HTTPException(status_code=422, detail="The uploaded file is empty.")
        if language not in {"en", "ar"}:
            raise HTTPException(status_code=422, detail="language must be 'en' or 'ar'.")
        options = parse_cleaning_options(cleaning_options)
        scenario_inputs = parse_scenarios(scenarios)

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
            cleaned, _, _ = apply_cleaning(selected.df, options)
            response = workforce_scenario_frame(
                cleaned,
                filename=filename,
                sheet=selected.sheet_used or sheet or "Data",
                department_column=department_column,
                headcount_column=headcount_column,
                payroll_column=payroll_column,
                overtime_column=overtime_column or None,
                scenarios=scenario_inputs,
            )
            if language == "ar":
                response["limitations"] = [
                    "هذه حسابات افتراضية حتمية وليست توقعات؛ النسب المدخلة افتراضات تخطيطية.",
                    "تُطبّق تغييرات عدد الموظفين بالتناسب على المجموعات، ثم تُطبّق نسبة نمو الرواتب بشكل منفصل.",
                    "تُعدّل تكلفة العمل الإضافي وفق عدد الموظفين المتوقع ونسبة خفض العمل الإضافي.",
                    "لا تستنتج هذه الحسابات متطلبات نظام العمل أو التوطين، وليست استشارة امتثال.",
                    *(
                        ["تم إخفاء تفاصيل الإدارات لوجود مجموعة يقل عدد أفرادها عن خمسة؛ وتظل المجاميع العامة شاملة لجميع المجموعات الصالحة."]
                        if response["baseline"]["group_details_withheld"]
                        else []
                    ),
                ]
            return response

        try:
            return await asyncio.to_thread(build)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            logger.exception("Data Hub workforce scenario failed for %s", filename)
            raise HTTPException(status_code=422, detail="The selected data could not produce a valid scenario comparison.")

    @router.post("/skills")
    async def skills_data(
        file: UploadFile = File(...),
        sheet: str = Form(""),
        supply_role_column: str = Form(...),
        supply_skill_column: str = Form(...),
        supply_count_column: str = Form(""),
        demand_file: UploadFile | None = File(None),
        demand_sheet: str = Form(""),
        demand_role_column: str = Form(""),
        demand_skill_column: str = Form(""),
        demand_count_column: str = Form(""),
        cleaning_options: str = Form("[]"),
        language: str = Form("en"),
    ) -> dict[str, Any]:
        """Compare mapped workforce skill supply and demand; return aggregates only."""
        filename = Path(file.filename or "inventory.dat").name
        if Path(filename).suffix.lower() not in SUPPORTED_DATA_HUB_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Use CSV, XLS, XLSX, JSON, or JSON Lines.")
        raw = await file.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="Each file must be 25 MB or smaller.")
        if not raw:
            raise HTTPException(status_code=422, detail="The skills inventory file is empty.")

        demand_filename: str | None = None
        demand_raw: bytes | None = None
        if demand_file and demand_file.filename:
            demand_filename = Path(demand_file.filename).name
            if Path(demand_filename).suffix.lower() not in SUPPORTED_DATA_HUB_EXTENSIONS:
                raise HTTPException(status_code=415, detail="Use CSV, XLS, XLSX, JSON, or JSON Lines.")
            demand_raw = await demand_file.read(MAX_FILE_BYTES + 1)
            if len(demand_raw) > MAX_FILE_BYTES:
                raise HTTPException(status_code=413, detail="Each file must be 25 MB or smaller.")
            if not demand_raw:
                raise HTTPException(status_code=422, detail="The role/skill demand file is empty.")
            if len(raw) + len(demand_raw) > MAX_REQUEST_BYTES:
                raise HTTPException(status_code=413, detail="The combined upload limit is 50 MB.")
        if language not in {"en", "ar"}:
            raise HTTPException(status_code=422, detail="language must be 'en' or 'ar'.")
        options = parse_cleaning_options(cleaning_options)

        def build() -> dict[str, Any]:
            ingestion = ExcelIngestionEngine()

            def select_frame(content: bytes, source_name: str, sheet_name: str):
                results = ingestion.ingest_all(content, source_name)
                selected = next(
                    (
                        result for name, result in results
                        if result.success and result.df is not None and (not sheet_name or name == sheet_name)
                    ),
                    None,
                )
                if selected is None or selected.df is None:
                    raise ValueError("A selected skills worksheet could not be found or read.")
                cleaned, _, _ = apply_cleaning(selected.df, options)
                return cleaned, selected.sheet_used or sheet_name or "Data"

            supply_frame, actual_sheet = select_frame(raw, filename, sheet)
            demand_frame = None
            actual_demand_sheet = None
            if demand_raw is not None and demand_filename:
                demand_frame, actual_demand_sheet = select_frame(demand_raw, demand_filename, demand_sheet)
            response = workforce_skills_frame(
                supply_frame,
                filename=filename,
                sheet=actual_sheet,
                supply_role_column=supply_role_column,
                supply_skill_column=supply_skill_column,
                supply_count_column=supply_count_column or None,
                demand_frame=demand_frame,
                demand_filename=demand_filename,
                demand_sheet=actual_demand_sheet,
                demand_role_column=demand_role_column or None,
                demand_skill_column=demand_skill_column or None,
                demand_count_column=demand_count_column or None,
            )
            if language == "ar":
                response["limitations"] = [
                    "تُجمع أعداد العرض من العمود المحدد صراحةً، أو تُحتسب كسجل واحد لكل صف عند اختيار احتساب الصفوف.",
                    "التغطية هي العرض مقسوماً على الطلب المقدم صراحةً؛ ولا يُستنتج الطلب من بيانات المخزون.",
                    "إمكانية إعادة التوزيع حد إجمالي أعلى: تُطابق فوائض الأدوار مع فجواتها لكل مهارة، دون التوصية بأشخاص أو تحركات فردية.",
                    "يُعامل كل سجل كمهارة واحدة لكل صف؛ وتُطابق التسميات بعد إزالة المسافات وتجاهل حالة الأحرف.",
                    *(
                        ["حُجبت تفاصيل الأدوار والمهارات أو الإجماليات لأن مجموعة واحدة على الأقل تضم أقل من خمسة؛ ولا تُعاد سجلات على مستوى الأفراد."]
                        if response["group_details_withheld"]
                        else []
                    ),
                    *(
                        ["الطلب غير معروف لعدم تحديد جدول للطلب؛ ولا تُحسب الفجوات أو إمكانية إعادة التوزيع."]
                        if response["demand"]["status"] == "unknown"
                        else []
                    ),
                ]
            return response

        try:
            return await asyncio.to_thread(build)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            logger.exception("Data Hub workforce skills analysis failed for %s", filename)
            raise HTTPException(status_code=422, detail="The selected data could not produce a valid skills comparison.")

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
        language: str = Form("en"),
    ) -> Response:
        """Download a workbook of schema and aggregate findings—never raw rows."""
        if language not in {"en", "ar"}:
            raise HTTPException(status_code=422, detail="language must be 'en' or 'ar'.")
        profiles = await export_profiles(files, cleaning_options)
        try:
            content = await asyncio.to_thread(build_summary_xlsx, profiles, language)
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
