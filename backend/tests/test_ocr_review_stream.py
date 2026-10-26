from __future__ import annotations

import hashlib
import json
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import local_analysis_routes as routes
from backend.core.auth_session import AWIRole
from backend.core.local_auth import LocalUser
from backend.core.security_middleware import get_current_user
from backend.core.verified_table_review import reviewed_tables_from_json


RAW_PDF = b"%PDF-fixture-for-review-trust-boundary"
SOURCE_ID = hashlib.sha256(RAW_PDF).hexdigest()


def review_payload():
    return [{
        "source_id": SOURCE_ID, "scope": "reviewed_rows_only",
        "confirmed_headers": True, "columns": ["Category", "Revenue"],
        "rows": [
            {"page": 1, "values": ["Retail", "125"], "verified": True},
            {"page": 2, "values": ["Online", "75"], "verified": True},
        ],
    }]


def scanned_ingestion(raw, filename, progress=None):
    if progress:
        progress({"stage": "extracting", "page": 1, "total_pages": 2, "method": "ocr"})
    metadata = {"requires_numeric_review": True, "ocr_languages": "ara+eng", "pages": [
        {"page": 1, "method": "ocr", "confidence": 95, "low_confidence_numbers": 0},
        {"page": 2, "method": "ocr", "confidence": 96, "low_confidence_numbers": 0},
    ]}
    frame = pd.DataFrame({"PDF page": [1, 2], "PDF text": ["Revenue 1O0", "Revenue 7S"]})
    frame.attrs["pdf_extraction"] = metadata
    return {filename: frame}, {filename: set()}, [{
        "filename": filename, "source_filename": filename,
        "source_id": hashlib.sha256(raw).hexdigest(), "review_allowed": True,
        "rows": 2, "columns": list(frame.columns), "pdf_extraction": metadata,
        "review_preview": [{"page": 1, "text": "Revenue 1O0"}, {"page": 2, "text": "Revenue 7S"}],
    }]


class ReviewValidationTests(unittest.TestCase):
    def setUp(self):
        self.sources = {SOURCE_ID: {"eligible": True, "filename": "scan.pdf", "pages": {1, 2}}}

    def test_only_explicit_rows_form_a_new_source(self):
        label, frame, audit = reviewed_tables_from_json(json.dumps(review_payload()), self.sources)[0]
        self.assertIn("User-reviewed rows", label)
        self.assertEqual(len(frame), 2)
        self.assertNotIn("pdf_extraction", frame.attrs)
        self.assertTrue(audit["original_ocr_remains_unverified"])
        self.assertEqual(audit["row_pages"], [1, 2])

    def test_each_row_must_be_verified(self):
        payload = review_payload()
        payload[0]["rows"][1]["verified"] = False
        with self.assertRaisesRegex(ValueError, "every included row"):
            reviewed_tables_from_json(json.dumps(payload), self.sources)

    def test_review_requires_same_document_and_real_page(self):
        for key, value in [("source_id", "not-the-original"), ("page", 99)]:
            payload = review_payload()
            if key == "page":
                payload[0]["rows"][0]["page"] = value
            else:
                payload[0][key] = value
            with self.assertRaises(ValueError):
                reviewed_tables_from_json(json.dumps(payload), self.sources)

    def test_headers_scope_and_types_are_checked(self):
        invalid = review_payload()
        invalid[0]["columns"] = ["Revenue", "revenue"]
        with self.assertRaises(ValueError):
            reviewed_tables_from_json(json.dumps(invalid), self.sources)
        invalid = review_payload()
        invalid[0]["scope"] = "whole_document_verified"
        with self.assertRaises(ValueError):
            reviewed_tables_from_json(json.dumps(invalid), self.sources)


class ReviewAndStreamApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(routes.create_local_analysis_router())
        user = LocalUser("review-test-user", "test", "Test", "", AWIRole.SYSTEM_ADMIN, must_change_pw=False)
        self.app.dependency_overrides[get_current_user] = lambda: user

    def request(self, client, payload=None, stream=False):
        data = {"question": "Total Revenue", "use_cloud": "true"}
        if payload is not None:
            data["reviewed_tables"] = json.dumps(payload)
        return client.post(
            "/api/local/ai-business-analyst/agentic" + ("/stream" if stream else ""),
            data=data, files={"files": ("scan.pdf", RAW_PDF, "application/pdf")},
        )

    def test_reviewed_values_used_not_original_ocr(self):
        with patch.object(routes, "_ingest_analyst_upload", side_effect=scanned_ingestion), patch.object(
            routes, "_agentic_check_cloud_mode", side_effect=AssertionError("OCR/review must remain local"),
        ), TestClient(self.app) as client:
            result = self.request(client, review_payload())
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["answer"]["mode"], "tabular")
        self.assertIn("200.00", body["answer"]["key_evidence"][0]["value"])
        self.assertTrue(any("only the explicitly user-reviewed rows" in text for text in body["answer"]["limitations"]))
        audit = body["file_details"][-1]["reviewed_table"]
        self.assertEqual(audit["rows_confirmed"], 2)
        self.assertTrue(audit["original_ocr_remains_unverified"])

    def test_unreviewed_scans_stay_blocked(self):
        with patch.object(routes, "_ingest_analyst_upload", side_effect=scanned_ingestion), TestClient(self.app) as client:
            result = self.request(client)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["answer"]["evidence_level"], "insufficient")

    def test_invalid_review_is_an_explicit_error(self):
        payload = review_payload()
        payload[0]["rows"][0]["verified"] = False
        with patch.object(routes, "_ingest_analyst_upload", side_effect=scanned_ingestion), TestClient(self.app) as client:
            result = self.request(client, payload)
        self.assertEqual(result.status_code, 422)

    def test_review_cannot_bypass_personal_data_governance(self):
        payload = review_payload()
        payload[0]["columns"] = ["Employee Name", "Salary"]
        with patch.object(routes, "_ingest_analyst_upload", side_effect=scanned_ingestion), TestClient(self.app) as client:
            result = self.request(client, payload)
        self.assertEqual(result.status_code, 422)

    def test_stream_sends_page_events_and_result_without_registry(self):
        with patch.object(routes, "_ingest_analyst_upload", side_effect=scanned_ingestion), patch.object(
            routes, "_start_ocr_progress", side_effect=AssertionError("Streaming must not depend on a worker-local registry"),
        ), TestClient(self.app) as client:
            result = self.request(client, review_payload(), stream=True)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("text/event-stream", result.headers["content-type"])
        self.assertIn('event: progress\ndata: {"stage": "extracting", "page": 1', result.text)
        self.assertIn("event: result", result.text)
        self.assertIn("200.00", result.text)

    def test_stream_validation_failure_is_not_a_partial_success(self):
        payload = review_payload()
        payload[0]["source_id"] = "wrong-document"
        with patch.object(routes, "_ingest_analyst_upload", side_effect=scanned_ingestion), TestClient(self.app) as client:
            result = self.request(client, payload, stream=True)
        self.assertIn("event: error", result.text)
        self.assertNotIn("event: result", result.text)

    def test_stream_requires_authentication(self):
        self.app.dependency_overrides.clear()
        with TestClient(self.app) as client:
            result = self.request(client, stream=True)
        self.assertEqual(result.status_code, 401)


if __name__ == "__main__":
    unittest.main()
