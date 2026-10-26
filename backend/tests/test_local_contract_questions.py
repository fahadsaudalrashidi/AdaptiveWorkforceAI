from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.local_analysis_routes import create_local_analysis_router
from backend.core.ai_business_analyst_engine import answer_question
from backend.core.auth_session import AWIRole
from backend.core.local_auth import LocalUser
from backend.core.local_contract_questions import answer_contract_count
from backend.core.security_middleware import get_current_user
from backend.tests.test_local_file_analytics import _simple_searchable_pdf


QUESTION = "كم عقد منتهي؟"
CSV = b"ContractID,ContractStatus\nC1,Expired\nC2,Active\nC3,Expired\n"


class LocalContractPromptTests(unittest.TestCase):
    def answer(self, frame, question=QUESTION, sources=None):
        return answer_contract_count(question, sources or {"contracts.csv": frame})

    def test_arabic_and_english_count_explicit_statuses(self):
        frame = pd.read_csv(io.BytesIO(CSV))
        for question in [QUESTION, "كم عدد العقود المنتهية؟", "How many expired contracts?"]:
            with self.subTest(question=question):
                result = self.answer(frame, question)
                self.assertEqual(result.operation, "contract_expired_count")
                self.assertEqual(result.detail.splitlines()[0], "2")

    def test_arabic_headers_and_statuses(self):
        frame = pd.DataFrame({"رقم العقد": ["A", "B", "C"], "حالة العقد": ["منتهي", "ساري", "منتهية"]})
        self.assertEqual(self.answer(frame).detail.splitlines()[0], "2")

    def test_unique_contracts_not_duplicate_rows(self):
        frame = pd.DataFrame({"ContractID": ["A", "A", "B"], "ContractStatus": ["Expired", "Expired", "Active"]})
        self.assertEqual(self.answer(frame).detail.splitlines()[0], "1")
        frame.loc[1, "ContractStatus"] = "Active"
        self.assertEqual(self.answer(frame).operation, "clarify")

    def test_dates_use_explicit_reference_and_end_of_day_boundary(self):
        frame = pd.DataFrame({"ContractEndDate": ["2026-10-20", "2026-10-21", "2026-10-22"]})
        result = self.answer(frame, "كم عقد منتهي حتى 2026-10-21؟")
        self.assertEqual(result.detail.splitlines()[0], "1")
        self.assertIn("2026-10-21", result.detail)
        self.assertTrue(result.warnings)

    def test_ambiguous_dates_and_status_codes_are_not_guessed(self):
        for frame in [
            pd.DataFrame({"ContractEndDate": ["01/02/2026", "bad-date"]}),
            pd.DataFrame({"ContractStatus": ["1", "0"]}),
            pd.DataFrame({"ContractStatus": ["Expired", None]}),
            pd.DataFrame({"ContractEndDate": [["2026-01-01"]]}),
        ]:
            self.assertEqual(self.answer(frame).operation, "clarify")

    def test_unknown_filters_and_negation_do_not_return_unfiltered_counts(self):
        frame = pd.read_csv(io.BytesIO(CSV))
        for question in ["كم عقد منتهي في قسم المبيعات؟", "How many contracts are not expired?"]:
            self.assertEqual(self.answer(frame, question).operation, "clarify")

    def test_ocr_and_multiple_source_ambiguity_remain_safe(self):
        frame = pd.read_csv(io.BytesIO(CSV))
        result = self.answer(frame, sources={"a.csv": frame, "b.csv": frame})
        self.assertEqual(result.operation, "clarify")
        frame.attrs["pdf_extraction"] = {"requires_numeric_review": True}
        self.assertEqual(self.answer(frame).operation, "clarify")

    def test_counts_integrate_into_the_existing_local_answer(self):
        frame = pd.read_csv(io.BytesIO(CSV))
        result = answer_question(QUESTION, {}, use_llm=False, uploaded_frames={"contracts.csv": frame})
        self.assertEqual(result.matched_query_id, "local.contract_expired_count")
        self.assertIn("2", result.answer_text)
        self.assertIn("local_contract_questions", result.source_engine)


class UploadedContractApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(create_local_analysis_router())
        app.dependency_overrides[get_current_user] = lambda: LocalUser(
            "contract-test", "test", "Test", "", AWIRole.SYSTEM_ADMIN, must_change_pw=False,
        )
        self.app = app

    def test_stable_and_streaming_routes_analyze_arabic_csv_without_cloud(self):
        with patch("backend.api.local_analysis_routes._agentic_check_cloud_mode", side_effect=AssertionError("No paid provider")), TestClient(self.app) as client:
            status = client.get("/api/local/ai-business-analyst/agentic/status").json()
            self.assertTrue(status["streaming_supported"])
            for suffix in ("", "/stream"):
                response = client.post(
                    "/api/local/ai-business-analyst/agentic" + suffix,
                    data={"question": QUESTION}, files={"files": ("contracts.csv", CSV, "text/csv")},
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn('"detail":"Not Found"', response.text)
                self.assertIn("contract_expired_count", response.text)

    def test_excel_json_and_searchable_pdf_routes(self):
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        for row in [["ContractID", "ContractStatus"], ["A", "Expired"], ["B", "Active"]]:
            sheet.append(row)
        excel = io.BytesIO()
        workbook.save(excel)
        sources = [
            ("contracts.xlsx", excel.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("contracts.json", b'[{"ContractID":"A","ContractStatus":"Expired"},{"ContractID":"B","ContractStatus":"Active"}]', "application/json"),
            ("contracts.pdf", _simple_searchable_pdf([
                f"{identifier:<16}{status}" for identifier, status in [
                    ("ContractID", "ContractStatus"), ("A", "Expired"), ("B", "Active"),
                ]
            ]), "application/pdf"),
        ]
        with TestClient(self.app) as client:
            for filename, raw, mime in sources:
                with self.subTest(filename=filename):
                    response = client.post(
                        "/api/local/ai-business-analyst/agentic/stream",
                        data={"question": QUESTION}, files={"files": (filename, raw, mime)},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIn("event: result", response.text)
                    self.assertNotIn("event: error", response.text)
                    self.assertIn("contract_expired_count", response.text)


if __name__ == "__main__":
    unittest.main()
