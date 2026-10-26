from __future__ import annotations

import io
import unittest
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook

from backend.core.data_hub_engine import (
    apply_cleaning,
    build_summary_pdf,
    build_summary_xlsx,
    forecast_frame,
    profile_frame,
)


class DataHubProfileTests(unittest.TestCase):
    def test_profile_returns_schema_aggregates_and_withholds_sensitive_statistics(self):
        frame = pd.DataFrame({
            "Department": ["Operations"] * 9 + ["Finance"],
            "Monthly Cost": [100, 101, 98, 99, 102, 100, 103, 97, 99, 1000],
            "Employee Name": [f"Person {i}" for i in range(10)],
        })

        result = profile_frame(frame, filename="costs.csv", sheet="Data")

        cost = next(column for column in result["columns"] if column["name"] == "Monthly Cost")
        name = next(column for column in result["columns"] if column["name"] == "Employee Name")
        self.assertEqual(result["source_rows"], 10)
        self.assertEqual(cost["outlier_count"], 1)
        self.assertEqual(name["sensitive"], True)
        self.assertIsNone(name["numeric_summary"])
        self.assertFalse(any("Person" in str(value) for value in result.values()))
        self.assertEqual(result["anomalies"][0]["method"], "Tukey IQR fence (1.5 × IQR)")

    def test_cleaning_is_opt_in_and_discloses_changes(self):
        frame = pd.DataFrame({" Team ": [" Ops ", "Ops", None], "Empty": [None, None, None]})
        untouched, applied_none, counts_none = apply_cleaning(frame)
        self.assertEqual(len(untouched), 3)
        self.assertEqual(applied_none, [])

        cleaned, applied, counts = apply_cleaning(
            frame, ["trim_text", "remove_blank_rows", "remove_blank_columns", "remove_exact_duplicates"]
        )
        self.assertEqual(counts["source_rows"], 3)
        self.assertEqual(counts["analyzed_rows"], 1)
        self.assertEqual(counts["source_columns"], 2)
        self.assertEqual(counts["analyzed_columns"], 1)
        self.assertEqual(cleaned.columns.tolist(), [" Team "])
        self.assertEqual(cleaned.iloc[0, 0], "Ops")
        self.assertEqual({entry["id"] for entry in applied}, {
            "trim_text", "remove_blank_rows", "remove_blank_columns", "remove_exact_duplicates"
        })

    def test_monthly_forecast_has_observed_and_intervals(self):
        frame = pd.DataFrame({
            "Month": pd.date_range("2025-01-01", periods=12, freq="MS"),
            "Operating Budget": [100 + i * 10 for i in range(12)],
        })

        result = forecast_frame(
            frame,
            filename="budget.csv",
            sheet="Data",
            date_column="Month",
            metric_column="Operating Budget",
            aggregation="sum",
            horizon=3,
        )

        self.assertEqual(result["observation_count"], 12)
        self.assertEqual(result["forecast"][0]["period"], "2026-01")
        self.assertAlmostEqual(result["forecast"][0]["estimate"], 220, places=5)
        self.assertLessEqual(result["forecast"][0]["lower"], result["forecast"][0]["estimate"])
        self.assertGreaterEqual(result["forecast"][0]["upper"], result["forecast"][0]["estimate"])
        self.assertTrue(result["limitations"])

    def test_forecast_rejects_sensitive_measure_and_short_history(self):
        frame = pd.DataFrame({
            "Month": pd.date_range("2025-01-01", periods=12, freq="MS"),
            "Salary": [100 + i for i in range(12)],
        })
        with self.assertRaisesRegex(ValueError, "personal or post-event"):
            forecast_frame(frame, filename="hr.csv", sheet="Data", date_column="Month", metric_column="Salary")

        short = frame.iloc[:7].copy()
        short["Operating Budget"] = range(7)
        with self.assertRaisesRegex(ValueError, "At least 8"):
            forecast_frame(short, filename="budget.csv", sheet="Data", date_column="Month", metric_column="Operating Budget")

    def test_workbook_export_contains_no_source_records(self):
        profile = profile_frame(
            pd.DataFrame({"Department": ["Secret Division", "Secret Division"], "Cost": [10, 20]}),
            filename="internal.csv",
            sheet="Data",
        )
        content = build_summary_xlsx([profile])
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        values = [cell for row in workbook["Data Profile"].iter_rows(values_only=True) for cell in row]
        self.assertIn("Cost", values)
        self.assertNotIn("Secret Division", values)
        workbook.close()

    def test_pdf_export_is_a_valid_document_in_both_languages(self):
        profile = profile_frame(
            pd.DataFrame({"Department": ["Operations"] * 10, "Budget": list(range(10))}),
            filename="budget.csv",
            sheet="Data",
        )
        for language in ("en", "ar"):
            pdf = build_summary_pdf([profile], language)
            self.assertTrue(pdf.startswith(b"%PDF-"))
            self.assertGreater(len(pdf), 1000)


if __name__ == "__main__":
    unittest.main()
