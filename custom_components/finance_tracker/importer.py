"""Parse bulk expense imports from CSV and Excel workbooks."""

from __future__ import annotations

import base64
import csv
from io import BytesIO, StringIO
from pathlib import PurePosixPath
import zipfile
from xml.etree import ElementTree

from homeassistant.exceptions import HomeAssistantError

from .storage import RECURRENCE_TYPES

MAX_IMPORT_BYTES = 5 * 1024 * 1024
REQUIRED_COLUMNS = {"name", "category", "amount", "recurrence"}


def parse_expense_file(filename: str, encoded_content: str) -> list[dict]:
    """Decode and validate an uploaded CSV or XLSX expense file."""
    try:
        content = base64.b64decode(encoded_content, validate=True)
    except ValueError as err:
        raise HomeAssistantError("Import content is not valid base64") from err
    if not content:
        raise HomeAssistantError("Import file is empty")
    if len(content) > MAX_IMPORT_BYTES:
        raise HomeAssistantError("Import file must be 5 MB or smaller")

    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        rows = _parse_csv(content)
    elif lower_name.endswith(".xlsx"):
        rows = _parse_xlsx(content)
    else:
        raise HomeAssistantError("Only .csv and .xlsx files are supported")
    return _normalize_rows(rows)


def _parse_csv(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as err:
        raise HomeAssistantError("CSV files must use UTF-8 encoding") from err
    try:
        return list(csv.DictReader(StringIO(text)))
    except csv.Error as err:
        raise HomeAssistantError(f"Invalid CSV file: {err}") from err


def _parse_xlsx(content: bytes) -> list[dict[str, str]]:
    try:
        workbook = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as err:
        raise HomeAssistantError("Invalid Excel workbook") from err

    with workbook:
        names = set(workbook.namelist())
        if "xl/workbook.xml" not in names:
            raise HomeAssistantError("Excel workbook metadata is missing")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.text or "" for node in item.findall(".//{*}t"))
                for item in root.findall("{*}si")
            ]

        workbook_root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
        first_sheet = workbook_root.find(".//{*}sheet")
        if first_sheet is None:
            raise HomeAssistantError("Excel workbook does not contain a sheet")
        relationship_id = first_sheet.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        sheet_path = "xl/worksheets/sheet1.xml"
        relationships_path = "xl/_rels/workbook.xml.rels"
        if relationship_id and relationships_path in names:
            relationships = ElementTree.fromstring(workbook.read(relationships_path))
            for relationship in relationships.findall("{*}Relationship"):
                if relationship.get("Id") == relationship_id:
                    target = relationship.get("Target", "worksheets/sheet1.xml").lstrip("/")
                    sheet_path = (
                        target
                        if target.startswith("xl/")
                        else str(PurePosixPath("xl") / target)
                    )
                    break
        if sheet_path not in names:
            raise HomeAssistantError("The first Excel worksheet could not be read")

        sheet_root = ElementTree.fromstring(workbook.read(sheet_path))
        table: list[list[str]] = []
        for row in sheet_root.findall(".//{*}sheetData/{*}row"):
            values: dict[int, str] = {}
            for cell in row.findall("{*}c"):
                reference = cell.get("r", "A1")
                column = _column_index(reference)
                cell_type = cell.get("t")
                value_node = cell.find("{*}v")
                if cell_type == "inlineStr":
                    value = "".join(
                        node.text or "" for node in cell.findall(".//{*}t")
                    )
                elif value_node is None:
                    value = ""
                elif cell_type == "s":
                    index = int(value_node.text or "0")
                    value = shared_strings[index] if index < len(shared_strings) else ""
                else:
                    value = value_node.text or ""
                values[column] = value
            if values:
                width = max(values) + 1
                table.append([values.get(index, "") for index in range(width)])

    if not table:
        return []
    headers = [str(value).strip() for value in table[0]]
    return [
        {header: row[index] if index < len(row) else "" for index, header in enumerate(headers)}
        for row in table[1:]
        if any(str(value).strip() for value in row)
    ]


def _column_index(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha())
    value = 0
    for letter in letters.upper():
        value = value * 26 + ord(letter) - ord("A") + 1
    return max(0, value - 1)


def _normalize_rows(rows: list[dict]) -> list[dict]:
    if not rows:
        raise HomeAssistantError("Import file does not contain expense rows")
    if len(rows) > 1000:
        raise HomeAssistantError("Import files are limited to 1000 expense rows")

    normalized_rows: list[dict] = []
    for row_number, raw_row in enumerate(rows, start=2):
        row = {
            str(key).strip().lower(): str(value or "").strip()
            for key, value in raw_row.items()
            if key is not None
        }
        missing = [column for column in REQUIRED_COLUMNS if not row.get(column)]
        if missing:
            raise HomeAssistantError(
                f"Row {row_number} is missing: {', '.join(sorted(missing))}"
            )

        recurrence = row["recurrence"].lower().replace("-", "_").replace(" ", "_")
        if recurrence not in RECURRENCE_TYPES:
            raise HomeAssistantError(
                f"Row {row_number} has unsupported recurrence: {row['recurrence']}"
            )
        try:
            amount = float(row["amount"])
        except ValueError as err:
            raise HomeAssistantError(f"Row {row_number} has an invalid amount") from err
        if amount < 0:
            raise HomeAssistantError(f"Row {row_number} amount cannot be negative")

        expense = {
            "name": row["name"],
            "category": row["category"],
            "amount": amount,
            "recurrence": recurrence,
        }
        for field, minimum, maximum in (
            ("due_day", 1, 31),
            ("start_month", 1, 12),
            ("end_month", 1, 12),
            ("reminder_days", 0, 60),
        ):
            if not row.get(field):
                continue
            try:
                number = int(float(row[field]))
            except ValueError as err:
                raise HomeAssistantError(
                    f"Row {row_number} has an invalid {field}"
                ) from err
            if number < minimum or number > maximum:
                raise HomeAssistantError(
                    f"Row {row_number} {field} must be between {minimum} and {maximum}"
                )
            expense[field] = number
        for field in ("custom_months", "icon", "notes"):
            if row.get(field):
                expense[field] = row[field]
        if "custom_months" in expense:
            try:
                months = sorted(
                    {
                        int(value.strip())
                        for value in expense["custom_months"].split(",")
                        if value.strip()
                    }
                )
            except ValueError as err:
                raise HomeAssistantError(
                    f"Row {row_number} has invalid custom_months"
                ) from err
            if not months or any(month < 1 or month > 12 for month in months):
                raise HomeAssistantError(
                    f"Row {row_number} custom_months must contain values from 1 to 12"
                )
            expense["custom_months"] = ",".join(str(month) for month in months)
        if expense.get("start_month") and expense.get("end_month"):
            if expense["start_month"] > expense["end_month"]:
                raise HomeAssistantError(
                    f"Row {row_number} start_month cannot be after end_month"
                )
        normalized_rows.append(expense)

    return normalized_rows
