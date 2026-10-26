"""Real raster-PDF regressions. Network sockets are forbidden, including workers."""
from __future__ import annotations

from contextlib import contextmanager
import io
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import patch

import pandas as pd
import pypdfium2 as pdfium

from backend.core import local_pdf_ocr as ocr
from backend.core.excel_ingestion_engine import ExcelIngestionEngine
from backend.core.local_question_engine import analyze_local_question
from backend.tests.test_local_file_analytics import _simple_searchable_pdf

FIXTURES = Path(__file__).parent / "fixtures" / "pdf_ocr"

NETWORK_GUARD = """
import socket
_original_socket = socket.socket
class OfflineSocket(_original_socket):
    def __init__(self, family=socket.AF_INET, *args, **kwargs):
        if family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Network access forbidden in local OCR tests")
        super().__init__(family, *args, **kwargs)
socket.socket = OfflineSocket
def deny_network(*args, **kwargs):
    raise AssertionError("Network access forbidden in local OCR tests")
socket.create_connection = deny_network
socket.getaddrinfo = deny_network
"""


@contextmanager
def no_network():
    # sitecustomize applies the same guard to the isolated Python worker.
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "sitecustomize.py").write_text(NETWORK_GUARD)
        original = socket.socket

        class OfflineSocket(original):
            def __init__(self, family=socket.AF_INET, *args, **kwargs):
                if family in (socket.AF_INET, socket.AF_INET6):
                    raise AssertionError("Network access forbidden in local OCR tests")
                super().__init__(family, *args, **kwargs)

        with (
            patch.dict(os.environ, {"PYTHONPATH": directory + os.pathsep + os.environ.get("PYTHONPATH", "")}),
            patch("socket.socket", OfflineSocket),
            patch("socket.create_connection", side_effect=AssertionError("Network forbidden")),
            patch("socket.getaddrinfo", side_effect=AssertionError("Network forbidden")),
        ):
            yield


class LocalPdfOcrTests(unittest.TestCase):
    def setUp(self):
        self.offline = no_network()
        self.offline.__enter__()
        self.addCleanup(self.offline.__exit__, None, None, None)
        self.engine = ExcelIngestionEngine()

    def raw(self, name):
        return (FIXTURES / name).read_bytes()

    def ingest(self, name):
        result = self.engine.ingest(self.raw(name), name)
        self.assertTrue(result.success, result.error)
        return result

    def test_fixture_is_real_image_only_and_recognizes_english_offline(self):
        import pdfplumber
        with pdfplumber.open(io.BytesIO(self.raw("scanned_english.pdf"))) as pdf:
            self.assertFalse(pdf.pages[0].extract_text())
            self.assertTrue(pdf.pages[0].images)
        result = self.ingest("scanned_english.pdf")
        self.assertIn("1250", result.df.iloc[0]["PDF text"])
        self.assertIn("Quarterly", result.df.iloc[0]["PDF text"])
        info = result.df.attrs["pdf_extraction"]
        self.assertEqual(info["ocr_languages"], "ara+eng")
        self.assertEqual(info["pages"][0]["method"], "ocr")
        self.assertGreater(info["pages"][0]["confidence"], 70)
        answer = analyze_local_question("Summarize this document", {"scan.pdf": result.df})
        self.assertEqual(answer.operation, "document_search")
        self.assertIn("Page 1", answer.detail)

    def test_arabic_scan_retains_arabic_and_warns_about_uncertain_numbers(self):
        result = self.ingest("scanned_arabic.pdf")
        self.assertIn("الإيرادات", result.df.iloc[0]["PDF text"])
        self.assertIn("المبيعات", result.df.iloc[0]["PDF text"])
        self.assertGreater(result.df.attrs["pdf_extraction"]["pages"][0]["low_confidence_numbers"], 0)
        self.assertTrue(any("low-confidence" in warning for warning in result.warnings))
        answer = analyze_local_question("إجمالي الإيرادات", {"arabic.pdf": result.df})
        self.assertEqual(answer.operation, "clarify")
        self.assertTrue(answer.priority)

    def test_degraded_scan_never_calculates_numbers(self):
        result = self.ingest("scanned_low_quality.pdf")
        self.assertGreater(result.df.attrs["pdf_extraction"]["pages"][0]["low_confidence_numbers"], 0)
        answer = analyze_local_question("Total revenue", {"scan.pdf": result.df})
        self.assertEqual(answer.operation, "clarify")
        self.assertNotIn("1,966", answer.detail)

    def test_mixed_pages_keep_provenance_without_partial_native_totals(self):
        result = self.ingest("mixed_pages.pdf")
        pages = result.df.attrs["pdf_extraction"]["pages"]
        self.assertEqual([(p["page"], p["method"]) for p in pages], [(1, "native"), (2, "ocr")])
        self.assertEqual(result.df.attrs["pdf_text_pages"][1]["PDF page"], 2)
        answer = analyze_local_question("Total Sales", {"mixed.pdf": result.df})
        self.assertEqual(answer.operation, "clarify")
        self.assertNotIn("50.00", answer.detail)

    def test_searchable_heading_does_not_hide_scan_on_same_page(self):
        result = self.ingest("mixed_same_page.pdf")
        self.assertEqual(result.df.attrs["pdf_extraction"]["pages"][0]["method"], "native+ocr")
        text = result.df.iloc[0]["PDF text"]
        self.assertIn("Searchable report heading", text)
        self.assertIn("1250", text)

    def test_progress_reports_actual_pages(self):
        events = []
        result = self.engine.ingest(self.raw("mixed_pages.pdf"), "mixed.pdf", progress=events.append)
        self.assertTrue(result.success, result.error)
        self.assertEqual([e["page"] for e in events if e["stage"] == "extracting"], [1, 2])
        self.assertTrue(all(e["total_pages"] == 2 for e in events if e["stage"] == "extracting"))

    def test_low_confidence_numeric_token_is_not_hidden_by_high_page_average(self):
        tsv = "level\tblock_num\tpar_num\tline_num\tconf\ttext\n"
        tsv += "5\t1\t1\t1\t99\tRevenue\n5\t1\t1\t1\t40\t١٢٥٠\n5\t1\t1\t1\t99\tSAR\n"
        parsed = ocr._parse_tsv(tsv)
        self.assertEqual(parsed["low_confidence_numbers"], 1)
        self.assertIn("١٢٥٠", parsed["text"])
        self.assertEqual(parsed["confidence"], 79.33)

    def test_unavailable_ocr_and_missing_arabic_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.pdf").write_bytes(self.raw("scanned_english.pdf"))
            with patch.object(ocr.shutil, "which", return_value=None):
                with self.assertRaisesRegex(ValueError, "install Tesseract"):
                    ocr._worker(root)
            with patch.object(ocr.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "eng\nosd\n", "")):
                with self.assertRaisesRegex(ValueError, "Arabic.*English"):
                    ocr._worker(root)

    def test_page_byte_and_dimension_limits_are_explicit(self):
        with pdfium.PdfDocument(_simple_searchable_pdf("Report")) as page:
            many = pdfium.PdfDocument.new()
            for _ in range(21):
                many.import_pages(page)
            buffer = io.BytesIO()
            many.save(buffer)
            many.close()
        result = self.engine.ingest(buffer.getvalue(), "many.pdf")
        self.assertFalse(result.success)
        self.assertIn("20 pages", result.error)
        with patch.object(ocr, "MAX_BYTES", 16):
            with self.assertRaisesRegex(ValueError, "25 MB"):
                ocr.extract_pdf(b"x" * 17)
        huge = _simple_searchable_pdf("").replace(b"612 792", b"14000 14000")
        result = self.engine.ingest(huge, "huge.pdf")
        self.assertFalse(result.success)
        self.assertIn("megapixel", result.error)

    def test_document_timeout_kills_worker_and_removes_temporary_files(self):
        processes = []
        directories = []
        original = subprocess.Popen

        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            directories.append(Path(args[0][-1]))
            return process

        with patch.object(ocr.subprocess, "Popen", side_effect=launch), patch.object(ocr, "DOCUMENT_TIMEOUT", 0):
            with self.assertRaisesRegex(ValueError, "timed out"):
                ocr.extract_pdf(self.raw("scanned_english.pdf"))
        self.assertIsNotNone(processes[0].poll())
        self.assertFalse(directories[0].exists())

    def test_busy_workers_fail_without_starting_extra_process(self):
        with patch.object(ocr._SLOTS, "acquire", return_value=False), patch.object(ocr.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(ValueError, "busy"):
                ocr.extract_pdf(b"test")
            launch.assert_not_called()

    def test_malformed_pdf_has_no_partial_or_cloud_result(self):
        result = self.engine.ingest(b"%PDF-1.4\nbroken", "broken.pdf")
        self.assertFalse(result.success)
        self.assertIsNone(result.df)

    def test_every_table_and_text_source_is_governed_and_keeps_confidence(self):
        from backend.api import local_analysis_routes as routes
        with patch.object(routes._scanner, "scan", wraps=routes._scanner.scan) as scan:
            frames, _, details = routes._ingest_analyst_upload(self.raw("mixed_pages.pdf"), "mixed.pdf")
        self.assertEqual(scan.call_count, 2)
        self.assertEqual(len(frames), 2, details)
        for frame in frames.values():
            self.assertTrue(frame.attrs["pdf_extraction"]["requires_numeric_review"])
        for detail in details:
            self.assertEqual(detail["pdf_extraction"]["pages"][1]["page"], 2)
            self.assertNotIn("PDF text", detail["pdf_extraction"])
        from backend.core.ai_business_analyst_engine import analyze_uploaded_files
        self.assertEqual(analyze_uploaded_files(frames), {})

    def test_governance_failure_or_identifiers_block_all_document_sources(self):
        from backend.api import local_analysis_routes as routes
        frames, _, details = routes._ingest_analyst_upload(self.raw("scanned_identifiers.pdf"), "contacts.pdf")
        self.assertFalse(frames)
        self.assertTrue(any("personal identifiers" in d.get("error", "") for d in details), details)
        self.assertNotIn("example.com", str(details))
        with patch.object(routes._scanner, "scan", side_effect=RuntimeError("Scan unavailable")):
            frames, _, details = routes._ingest_analyst_upload(self.raw("mixed_pages.pdf"), "mixed.pdf")
        self.assertFalse(frames)
        self.assertTrue(all(d.get("error") for d in details))

    def test_governance_leakage_finding_cannot_be_ignored(self):
        from backend.api import local_analysis_routes as routes
        scan = routes._scanner.scan

        def blocked(**kwargs):
            report = scan(**kwargs)
            report.leakage_columns_detected = ["PDF text"]
            return report

        with patch.object(routes._scanner, "scan", side_effect=blocked):
            frames, _, details = routes._ingest_analyst_upload(self.raw("mixed_pages.pdf"), "mixed.pdf")
        self.assertFalse(frames)
        self.assertTrue(all("Governance blocked" in d["error"] for d in details))

    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.api.local_analysis_routes import create_local_analysis_router
        from backend.core.auth_session import AWIRole
        from backend.core.local_auth import LocalUser
        from backend.core.security_middleware import get_current_user
        app = FastAPI()
        app.include_router(create_local_analysis_router())
        user = LocalUser("ocr-user", "ocr", "OCR", "", AWIRole.SYSTEM_ADMIN, must_change_pw=False)
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app), user

    def test_api_ocr_is_offline_even_with_explicit_cloud_flag_and_progress_is_owner_only(self):
        from backend.api import local_analysis_routes as routes
        from backend.core.cloud_llm_client import CloudModeStatus
        client, user = self.client()
        progress_id = str(uuid.uuid4())
        with (
            patch.object(routes, "_agentic_check_cloud_mode", side_effect=AssertionError("No cloud")),
            patch.object(routes, "_agentic_cloud_mode_configuration", return_value=CloudModeStatus(True, False, "Opt-in", "", "test")),
            client,
        ):
            self.assertEqual(client.get(f"/api/local/ai-business-analyst/ocr-progress/{progress_id}").status_code, 404)
            response = client.post(
                "/api/local/ai-business-analyst/agentic",
                data={"question": "Total revenue", "use_cloud": "true", "progress_id": progress_id},
                files={"files": ("scan.pdf", self.raw("scanned_low_quality.pdf"), "application/pdf")},
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["mode"], "local_fallback")
            self.assertIn("clarification", body["answer"]["answer_text"])
            self.assertTrue(body["file_details"][0]["pdf_extraction"]["requires_numeric_review"])
            progress_url = f"/api/local/ai-business-analyst/ocr-progress/{progress_id}"
            event = client.get(progress_url).json()
            self.assertEqual(event["stage"], "complete")
            self.assertEqual(event["page"], 1)
            self.assertNotIn("owner", event)
            with routes._OCR_PROGRESS_LOCK:
                routes._OCR_PROGRESS[progress_id]["owner"] = "someone-else"
            self.assertEqual(client.get(progress_url).status_code, 404)
            with routes._OCR_PROGRESS_LOCK:
                routes._OCR_PROGRESS[progress_id]["owner"] = user.user_id
                routes._OCR_PROGRESS[progress_id]["updated"] = 0
            self.assertEqual(client.get(progress_url).status_code, 404)

    def test_progress_requires_authentication_and_valid_id(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.api.local_analysis_routes import create_local_analysis_router
        app = FastAPI()
        app.include_router(create_local_analysis_router())
        with TestClient(app) as client:
            response = client.get(f"/api/local/ai-business-analyst/ocr-progress/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 401)
        client, _ = self.client()
        with client:
            response = client.post("/api/local/ai-business-analyst/agentic",
                                   data={"question": "Total sales", "progress_id": "invalid"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
