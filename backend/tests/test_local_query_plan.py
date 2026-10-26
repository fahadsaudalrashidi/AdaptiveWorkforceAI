"""Regression coverage for the strict local filtered/comparative query path."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import pandas as pd

from backend.core.ai_business_analyst_engine import answer_question, analyst_answer_to_dict
from backend.core.local_question_engine import analyze_local_question


class LocalQueryPlanTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "Sales": [10.0, 20.0, None, 40.0, 50.0],
            "Region": ["West", "East", "West", None, "West"],
            "Date": ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01", None],
            "Units": [1, 2, 3, 4, None],
            "Email": ["private@example.invalid"] * 5,
        })
        self.files = {"sales.csv": self.frame}

    def ask(self, question, files=None, pii=None):
        return analyze_local_question(question, self.files if files is None else files, pii)

    def cohort(self, answer, index=0):
        self.assertNotEqual(answer.operation, "clarify", answer.text)
        return answer.query_audit["cohorts"][index]

    def test_categorical_filter_missing_measure_and_counts(self):
        answer = self.ask('total "Sales" where "Region" = "West"')
        audit = self.cohort(answer)
        self.assertEqual(audit["value"], 60)
        self.assertEqual((audit["source_rows"], audit["matched_rows"], audit["included_rows"], audit["excluded_rows"]), (5, 3, 2, 3))
        self.assertEqual((audit["missing_filter_rows"], audit["missing_measure_rows"]), (1, 1))
        self.assertEqual(audit["filters"][0]["column"], "Region")

    def test_missing_filter_never_matches_not_equal(self):
        audit = self.cohort(self.ask('count records where "Region" != "East"'))
        self.assertEqual(audit["value"], 3)
        self.assertEqual(audit["excluded_rows"], 2)
        self.assertEqual(audit["missing_filter_rows"], 1)

    def test_all_allowlisted_numeric_operators(self):
        for op, expected in [("=", 1), ("!=", 3), (">", 2), (">=", 3), ("<", 1), ("<=", 2)]:
            with self.subTest(op=op):
                audit = self.cohort(self.ask(f'count records where "Units" {op} 2'))
                self.assertEqual(audit["value"], expected)
                self.assertEqual(audit["missing_filter_rows"], 1)

    def test_large_numbers_cannot_silently_overflow_or_round_thresholds(self):
        frame = self.frame.assign(Sales=[2**63 - 1] * 5)
        self.assertEqual(self.ask('total "Sales" where "Region" = "West"', {"s.csv": frame}).operation, "clarify")
        frame = self.frame.assign(Sales=[2**52] * 5)
        self.assertEqual(self.ask('total "Sales" where "Region" = "West"', {"s.csv": frame}).operation, "clarify")
        self.assertEqual(self.ask('count records where "Sales" = 9007199254740993').operation, "clarify")

    def test_non_scalar_categories_require_clarification(self):
        frame = self.frame.assign(Region=[["West"]] * 5)
        self.assertEqual(self.ask('total "Sales" where "Region" = "West"', {"s.csv": frame}).operation, "clarify")

    def test_numeric_and_date_conditions_average(self):
        audit = self.cohort(self.ask('average "Sales" where "Units" >= 1 and "Date" <= "2025-02-01"'))
        self.assertEqual(audit["value"], 15)
        self.assertEqual(audit["included_rows"], 2)
        self.assertEqual(len(audit["filters"]), 2)

    def test_exact_column_names_without_quotes_are_supported(self):
        audit = self.cohort(self.ask('total Sales where Region = "West"'))
        self.assertEqual(audit["value"], 60)

    def test_comparison_preserves_both_cohorts_and_direction(self):
        answer = self.ask('compare total "Sales" where "Region" = "West" versus "Region" = "East"')
        self.assertEqual(self.cohort(answer)["value"], 60)
        self.assertEqual(self.cohort(answer, 1)["value"], 20)
        self.assertEqual(answer.query_audit["difference"], 40)
        self.assertIn("cohort 1 minus cohort 2", answer.detail)

    def test_count_and_average_comparisons(self):
        for operation, expected in [("count records", [3, 1]), ('average "Sales"', [30, 20])]:
            with self.subTest(operation=operation):
                answer = self.ask(f'compare {operation} where "Region" = "West" versus "Region" = "East"')
                self.assertEqual([c["value"] for c in answer.query_audit["cohorts"]], expected)

    def test_empty_total_and_average_are_not_zero_or_nan(self):
        for op in ["total", "average"]:
            answer = self.ask(f'{op} "Sales" where "Units" > 100')
            self.assertIsNone(self.cohort(answer)["value"])
            self.assertEqual(self.cohort(answer)["included_rows"], 0)
            self.assertIn("No matching numeric records", answer.detail)
            self.assertNotIn("nan", answer.detail)
        self.assertEqual(self.cohort(self.ask('count records where "Units" > 100'))["value"], 0)

    def test_all_missing_measure_does_not_invent_a_total(self):
        frame = self.frame.copy()
        frame["Sales"] = None
        audit = self.cohort(self.ask('total "Sales" where "Region" = "West"', {"sales.csv": frame}))
        self.assertIsNone(audit["value"])
        self.assertEqual(audit["missing_measure_rows"], 3)

    def test_no_difference_when_one_cohort_has_no_numeric_values(self):
        answer = self.ask('compare total "Sales" where "Units" > 100 versus "Region" = "West"')
        self.assertNotIn("difference", answer.query_audit)

    def test_date_filter_rejects_ambiguous_mixed_invalid_and_timezone_dates(self):
        for dates in [
            ["01/02/2025"] * 5,
            ["2025-01-01", "02/03/2025", None, None, None],
            ["2025-02-30"] * 5,
            pd.date_range("2025-01-01", periods=5, tz="UTC"),
        ]:
            with self.subTest(dates=str(dates)):
                frame = self.frame.assign(Date=dates)
                answer = self.ask('total "Sales" where "Date" >= "2025-01-01"', {"sales.csv": frame})
                self.assertEqual(answer.operation, "clarify")
                self.assertIsNone(answer.query_audit)

    def test_invalid_or_ambiguous_date_literals_require_clarification(self):
        for value in ["01/02/2025", "2025-02-30", "yesterday", "2025"]:
            with self.subTest(value=value):
                self.assertEqual(self.ask(f'total "Sales" where "Date" = "{value}"').operation, "clarify")

    def test_multiple_sources_require_exact_name_even_with_different_columns(self):
        files = {**self.files, "other.xlsx::Sheet": pd.DataFrame({"Other": [100]})}
        for suffix in ["", ' from "sales"', ' from "missing.csv"']:
            answer = self.ask(f'total "Sales"{suffix} where "Region" = "West"', files)
            self.assertEqual(answer.operation, "clarify")
        answer = self.ask('total "Sales" from "sales.csv" where "Region" = "West"', files)
        self.assertEqual(self.cohort(answer)["value"], 60)
        self.assertEqual(answer.query_audit["source_file"], "sales.csv")

    def test_ambiguous_and_partial_columns_do_not_guess(self):
        for frame, question in [
            (self.frame.assign(**{"Gross Sales": [100] * 5}).rename(columns={"Sales": "Net Sales"}), 'total "Sales" where "Region" = "West"'),
            (self.frame.assign(sales=[100] * 5), 'total "Sales" where "Region" = "West"'),
            (pd.DataFrame([[1, 2]], columns=["Sales", "Sales"]), 'total "Sales" where "Sales" > 0'),
        ]:
            with self.subTest(question=question):
                self.assertEqual(self.ask(question, {"s.csv": frame}).operation, "clarify")

    def test_personal_data_cannot_be_a_measure_filter_or_comparison(self):
        for question in [
            'total "Email" where "Region" = "West"',
            'total "Sales" where "Email" = "private@example.invalid"',
            'compare total "Sales" where "Region" = "West" versus "Email" = "private@example.invalid"',
            'total "Sales" where "Region" = "West"',
        ]:
            pii = {"sales.csv": {"Region"}} if '"Email"' not in question else None
            answer = self.ask(question, pii=pii)
            self.assertEqual(answer.operation, "clarify")
            self.assertIn("personal-data", answer.text)
            self.assertNotIn("private@example.invalid", answer.text + answer.detail)
            self.assertIsNone(answer.query_audit)

    def test_unsupported_conditions_are_never_partly_applied(self):
        questions = [
            'total "Sales" where "Region" = "West" or "Units" > 1',
            'total "Sales" where "Units" > 1 and',
            'total "Sales" where "Units" > 1 order by "Sales"',
            'total "Sales" where "Units" > 1; SELECT * FROM data',
            'total "Sales" where "Units" > __import__("os").system("false")',
            'total "Sales" where "Units" > 1 + 2',
            'total "Sales" where "Region" in ("West")',
            'total "Sales" where "Region" = "west"',
            'total "Sales" where "Region" = "West" versus "Region" = "East"',
            'compare total "Sales" where "Region" = "West"',
            'compare total "Sales" where "Region" = "West" versus "Region" = "East" versus "Units" > 1',
            'median "Sales" where "Region" = "West"',
            'total Sales after 2025-01-01',
            'total Sales between 1 and 10',
            'total Sales ratio Units',
            'count Sales where "Region" = "West"',
        ]
        for question in questions:
            with self.subTest(question=question):
                answer = self.ask(question)
                self.assertEqual(answer.operation, "clarify")
                self.assertEqual(answer.detail, "")
                self.assertIsNone(answer.query_audit)

    def test_quoted_keywords_are_data_not_operators(self):
        frame = self.frame.assign(Region=["West and East versus North"] * 5)
        audit = self.cohort(self.ask('total "Sales" where "Region" = "West and East versus North"', {"s.csv": frame}))
        self.assertEqual(audit["value"], 120)

    def test_invalid_nonfinite_locale_and_percentage_numbers_fail_closed(self):
        for value in ["bad", "1,234", "1,23", "25%", "1S", float("inf"), True]:
            with self.subTest(value=value):
                frame = self.frame.copy()
                frame["Sales"] = [value] * 5
                self.assertEqual(self.ask('total "Sales" where "Region" = "West"', {"s.csv": frame}).operation, "clarify")
        # One bad cell must not be hidden by a high numeric majority.
        frame = pd.DataFrame({"Sales": [1] * 99 + ["bad"], "Region": ["West"] * 100})
        self.assertEqual(self.ask('total "Sales" where "Region" = "West"', {"s.csv": frame}).operation, "clarify")

    def test_explicit_currency_is_preserved_without_conversion(self):
        frame = self.frame.copy()
        frame["Sales"] = ["SAR 10", "SAR 20", None, "SAR 40", "SAR 50"]
        answer = self.ask('total "Sales" where "Region" = "West"', {"s.csv": frame})
        self.assertEqual(self.cohort(answer)["value"], 60)
        self.assertEqual(answer.query_audit["currency"], "SAR")
        self.assertIn("SAR", answer.detail)

    def test_ambiguous_mixed_and_missing_currency_fail_closed(self):
        for frame in [
            self.frame.assign(Sales=["$10"] * 5),
            self.frame.assign(Currency=["USD", "EUR", "USD", "USD", "USD"]),
            self.frame.assign(Currency=["USD", None, "USD", "USD", "USD"]),
            self.frame.assign(Sales=["SAR 10", "EUR 20", None, "SAR 40", "SAR 50"]),
            self.frame.assign(Currency=["XXX"] * 5),
        ]:
            with self.subTest(frame=str(frame)):
                self.assertEqual(self.ask('total "Sales" where "Region" = "West"', {"s.csv": frame}).operation, "clarify")

    def test_scanned_numbers_still_require_verification(self):
        self.frame.attrs["pdf_extraction"] = {"requires_numeric_review": True}
        answer = self.ask('total "Sales" where "Region" = "West"')
        self.assertEqual(answer.operation, "clarify")
        self.assertIsNone(answer.query_audit)

    def test_source_and_cohort_evidence_survive_analyst_serialization_without_llm(self):
        with patch("backend.core.ai_business_analyst_engine.phrase_with_ollama", side_effect=AssertionError("No LLM for local queries")):
            answer = answer_question(
                'compare total "Sales" where "Region" = "West" versus "Region" = "East"',
                {}, use_llm=True, uploaded_frames=self.files,
            )
        body = json.loads(json.dumps(analyst_answer_to_dict(answer), allow_nan=False))
        self.assertEqual(body["query_audit"]["source_file"], "sales.csv")
        self.assertEqual(body["query_audit"]["measure"], "Sales")
        self.assertEqual(len(body["query_audit"]["cohorts"]), 2)
        self.assertIn("Source: sales.csv", body["key_evidence"][0]["label"])
        self.assertTrue(any("applied filters" in s for s in body["limitations"]))
        self.assertEqual(body["matched_query_id"], "local.comparison")

    def test_failed_plan_cannot_fall_back_to_registry(self):
        answer = answer_question('total revenue where "Region" = "West"', {}, uploaded_frames=self.files)
        self.assertEqual(answer.evidence_level, "insufficient")
        self.assertEqual(answer.matched_query_id, "local.clarify")
        self.assertIsNone(answer.query_audit)

    def test_api_keeps_filter_evidence_and_does_not_contact_configured_cloud(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.api.local_analysis_routes import create_local_analysis_router
        from backend.core.auth_session import AWIRole
        from backend.core.cloud_llm_client import CloudModeStatus
        from backend.core.local_auth import LocalUser
        from backend.core.security_middleware import get_current_user

        app = FastAPI()
        app.include_router(create_local_analysis_router())
        user = LocalUser("test-user", "test", "Test", "", AWIRole.SYSTEM_ADMIN, must_change_pw=False)
        app.dependency_overrides[get_current_user] = lambda: user
        configured = CloudModeStatus(True, False, "Explicit opt-in required", "(test)", "test-model")
        with (
            patch("backend.api.local_analysis_routes._agentic_check_cloud_mode", side_effect=AssertionError("Cloud must not be contacted")),
            patch("backend.api.local_analysis_routes._agentic_cloud_mode_configuration", return_value=configured),
            TestClient(app) as client,
        ):
            for endpoint in ["agentic", ""]:
                with self.subTest(endpoint=endpoint):
                    response = client.post(
                        "/api/local/ai-business-analyst" + ("/" + endpoint if endpoint else ""),
                        data={"question": 'compare total "Sales" where "Region" = "West" versus "Region" = "East"', "use_llm": "false"},
                        files={"files": ("sales.csv", b"Region,Sales\nWest,10\nEast,20\nWest,\n", "text/csv")},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    body = response.json()
                    self.assertEqual(body["answer"]["query_audit"]["source_file"], "sales.csv")
                    cohorts = body["answer"]["query_audit"]["cohorts"]
                    self.assertEqual([c["value"] for c in cohorts], [10, 20])
                    self.assertEqual(cohorts[0]["missing_measure_rows"], 1)


if __name__ == "__main__":
    unittest.main()
