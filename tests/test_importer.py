"""Tests for CSV and Excel bulk expense parsing."""

from __future__ import annotations

import base64
from io import BytesIO
import importlib.util
import sys
import unittest
import zipfile

from test_storage import PACKAGE_NAME, ROOT, _load_storage_module


_load_storage_module()
qualified_name = f"{PACKAGE_NAME}.importer"
spec = importlib.util.spec_from_file_location(
    qualified_name,
    ROOT / "custom_components" / "finance_tracker" / "importer.py",
)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load importer module")
importer = importlib.util.module_from_spec(spec)
sys.modules[qualified_name] = importer
spec.loader.exec_module(importer)


class ExpenseImporterTests(unittest.TestCase):
    def test_parse_csv_expenses(self) -> None:
        content = (
            "name,category,amount,recurrence,due_day,custom_months,notes\n"
            "Electricity,Utilities,2500,monthly,15,,Power bill\n"
            'Maintenance,Home,3000,custom_months,5,"1,4,7,10",Quarterly\n'
        ).encode()

        rows = importer.parse_expense_file(
            "expenses.csv", base64.b64encode(content).decode()
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["amount"], 2500.0)
        self.assertEqual(rows[0]["due_day"], 15)
        self.assertEqual(rows[1]["recurrence"], "custom_months")
        self.assertEqual(rows[1]["custom_months"], "1,4,7,10")

    def test_parse_first_excel_worksheet(self) -> None:
        workbook = BytesIO()
        rows = [
            ["name", "category", "amount", "recurrence", "due_day"],
            ["Rent", "Housing", "25000", "monthly", "1"],
        ]
        sheet_rows = []
        for row_index, row in enumerate(rows, start=1):
            cells = []
            for column_index, value in enumerate(row):
                reference = f"{chr(ord('A') + column_index)}{row_index}"
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
                )
            sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

        with zipfile.ZipFile(workbook, "w") as archive:
            archive.writestr(
                "xl/workbook.xml",
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Expenses" sheetId="1" r:id="rId1"/></sheets></workbook>',
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>',
            )

        parsed = importer.parse_expense_file(
            "expenses.xlsx", base64.b64encode(workbook.getvalue()).decode()
        )

        self.assertEqual(parsed[0]["name"], "Rent")
        self.assertEqual(parsed[0]["category"], "Housing")
        self.assertEqual(parsed[0]["amount"], 25000.0)
        self.assertEqual(parsed[0]["due_day"], 1)

    def test_reject_invalid_rows_before_import(self) -> None:
        content = b"name,category,amount,recurrence\nRent,Housing,nope,monthly\n"

        with self.assertRaisesRegex(Exception, "invalid amount"):
            importer.parse_expense_file(
                "expenses.csv", base64.b64encode(content).decode()
            )


if __name__ == "__main__":
    unittest.main()
