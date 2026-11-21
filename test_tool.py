"""Automated regression tests for the ISO 26262 Agent's Excel Tool.

Run from the repository root (Python 3.12+, openpyxl installed):
    python -m unittest -v test_tool.py

These tests check project-defined SG/FSR/TSR Excel structure and ID links.
They do not evaluate ISO 26262 clauses or standards compliance.
"""

from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook


checker = importlib.import_module("tools.traceability_check")


class TraceabilityCheckTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="iso26262_tool_test_")
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        active_patch = patch.object(checker, "DATA_DIR", self.data_dir)
        active_patch.start()
        self.addCleanup(active_patch.stop)

    def make_xlsx(
        self,
        sg=None,
        fsr=None,
        tsr=None,
        filename="case.xlsx",
        headers=None,
        omit_sheet=None,
    ):
        sg = [] if sg is None else sg
        fsr = [] if fsr is None else fsr
        tsr = [] if tsr is None else tsr
        default_headers = {
            "SG": ["ID", "Description"],
            "FSR": ["ID", "SG_ID", "Description"],
            "TSR": ["ID", "FSR_ID", "Description"],
        }
        if headers:
            default_headers.update(headers)
        wb = Workbook()
        initial = wb.active
        initial.title = "SG" if omit_sheet != "SG" else "Placeholder"
        for name, rows in (("SG", sg), ("FSR", fsr), ("TSR", tsr)):
            if name == omit_sheet:
                continue
            ws = initial if name == "SG" else wb.create_sheet(name)
            ws.append(default_headers[name])
            for row in rows:
                ws.append(row)
        target = self.data_dir / filename
        wb.save(target)
        wb.close()
        return filename

    def check(self, **kwargs):
        return checker.traceability_check(self.make_xlsx(**kwargs))

    @staticmethod
    def types(result):
        return [item["type"] for item in result.get("issues", [])]

    def test_01_valid_workbook_has_no_issues(self):
        result = self.check(
            sg=[["SG-001", "Goal 1"], ["SG-002", "Goal 2"]],
            fsr=[["FSR-001", "SG-001", "FSR 1"], ["FSR-002", "SG-002", "FSR 2"]],
            tsr=[["TSR-001", "FSR-001", "TSR 1"], ["TSR-002", "FSR-002", "TSR 2"]],
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"], {"SG_count": 2, "FSR_count": 2, "TSR_count": 2, "issue_count": 0})
        self.assertEqual(result["issues"], [])

    def test_02_fsr_without_tsr_retains_excel_row(self):
        result = self.check(
            sg=[["SG-001", "Goal 1"]],
            fsr=[["FSR-001", "SG-001", "FSR 1"], ["FSR-002", "SG-001", "FSR 2"]],
            tsr=[["TSR-001", "FSR-001", "TSR 1"]],
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["issue_count"], 1)
        self.assertEqual(result["issues"][0]["type"], "FSR_WITHOUT_TSR")
        self.assertEqual(result["issues"][0]["requirement"], "FSR-002")
        self.assertEqual(result["issues"][0]["row"], 3)

    def test_03_sg_without_fsr(self):
        result = self.check(sg=[["SG-001", "Goal"]])
        self.assertEqual(result["status"], "success")
        self.assertIn("SG_WITHOUT_FSR", self.types(result))

    def test_04_invalid_sg_reference(self):
        result = self.check(
            sg=[["SG-001", "Goal"]],
            fsr=[["FSR-001", "SG-999", "FSR"]],
            tsr=[["TSR-001", "FSR-001", "TSR"]],
        )
        self.assertEqual(result["status"], "success")
        self.assertIn("INVALID_SG_REFERENCE", self.types(result))

    def test_05_invalid_fsr_reference(self):
        result = self.check(
            sg=[["SG-001", "Goal"]],
            fsr=[["FSR-001", "SG-001", "FSR"]],
            tsr=[["TSR-001", "FSR-999", "TSR"]],
        )
        self.assertEqual(result["status"], "success")
        self.assertIn("INVALID_FSR_REFERENCE", self.types(result))

    def test_06_duplicate_fsr_is_ambiguous_without_false_missing_sg_link(self):
        result = self.check(
            sg=[["SG-001", "Goal"]],
            fsr=[["FSR-001", "SG-001", "A"], ["FSR-001", "SG-001", "B"]],
            tsr=[["TSR-001", "FSR-001", "TSR"]],
        )
        self.assertEqual(result["status"], "success")
        self.assertCountEqual(self.types(result), ["DUPLICATE_FSR_ID", "AMBIGUOUS_FSR_REFERENCE"])
        self.assertEqual(result["summary"]["issue_count"], 2)

    def test_07_duplicate_sg_is_ambiguous(self):
        result = self.check(
            sg=[["SG-001", "Goal A"], ["SG-001", "Goal B"]],
            fsr=[["FSR-001", "SG-001", "FSR"]],
            tsr=[["TSR-001", "FSR-001", "TSR"]],
        )
        self.assertEqual(result["status"], "success")
        self.assertCountEqual(self.types(result), ["DUPLICATE_SG_ID", "AMBIGUOUS_SG_REFERENCE"])

    def test_08_missing_id_and_description(self):
        result = self.check(
            sg=[["SG-001", "Goal"]],
            fsr=[["FSR-001", "SG-001", None]],
            tsr=[[None, "FSR-001", "TSR"]],
        )
        self.assertEqual(result["status"], "success")
        self.assertCountEqual(self.types(result), ["MISSING_DESCRIPTION", "MISSING_ID"])
        self.assertTrue(all(issue["row"] == 2 for issue in result["issues"]))

    def test_09_blank_row_is_ignored(self):
        result = self.check(
            sg=[["SG-001", "Goal"], [None, None]],
            fsr=[["FSR-001", "SG-001", "FSR"]],
            tsr=[["TSR-001", "FSR-001", "TSR"]],
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["SG_count"], 1)
        self.assertEqual(result["summary"]["issue_count"], 0)

    def test_10_no_requirement_data_is_error(self):
        result = self.check()
        self.assertEqual(result["status"], "error")
        self.assertIn("No requirement data", result["message"])

    def test_11_missing_sheet_is_error(self):
        result = self.check(omit_sheet="TSR")
        self.assertEqual(result["status"], "error")
        self.assertIn("Missing sheet: TSR", result["message"])

    def test_12_missing_required_column_is_error(self):
        result = self.check(headers={"FSR": ["ID", "Description"]})
        self.assertEqual(result["status"], "error")
        self.assertIn("FSR missing columns", result["message"])
        self.assertIn("SG_ID", result["message"])

    def test_13_duplicate_required_header_is_error(self):
        result = self.check(headers={"FSR": ["ID", "SG_ID", "Description", "SG_ID"]})
        self.assertEqual(result["status"], "error")
        self.assertIn("duplicate columns", result["message"])

    def test_14_nonexistent_file_is_error(self):
        result = checker.traceability_check("not_found.xlsx")
        self.assertEqual(result["status"], "error")
        self.assertIn("File not found", result["message"])

    def test_15_path_traversal_is_rejected(self):
        result = checker.traceability_check("../outside.xlsx")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid file path", result["message"])

    def test_16_wrong_extension_is_rejected(self):
        result = checker.traceability_check("test.xlsm")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid file path", result["message"])

    def test_17_invalid_xlsx_is_error(self):
        (self.data_dir / "broken.xlsx").write_text("not a workbook", encoding="utf-8")
        result = checker.traceability_check("broken.xlsx")
        self.assertEqual(result["status"], "error")
        self.assertIn("Excel parsing failed", result["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
