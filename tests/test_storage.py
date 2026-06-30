"""Regression tests for the SQLite-backed finance tracker storage."""

from __future__ import annotations

import importlib.util
from contextlib import closing
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "custom_components.finance_tracker"


def _load_storage_module():
    """Load storage.py with the minimal Home Assistant API it requires."""
    homeassistant = types.ModuleType("homeassistant")
    homeassistant_core = types.ModuleType("homeassistant.core")
    homeassistant_exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistant:
        """Type placeholder used by the storage module."""

    class HomeAssistantError(Exception):
        """Test replacement for Home Assistant's user-facing error."""

    homeassistant_core.HomeAssistant = HomeAssistant
    homeassistant_exceptions.HomeAssistantError = HomeAssistantError
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules["homeassistant.core"] = homeassistant_core
    sys.modules["homeassistant.exceptions"] = homeassistant_exceptions

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT / "custom_components" / "finance_tracker")]
    sys.modules[PACKAGE_NAME] = package

    for module_name in ("const", "storage"):
        qualified_name = f"{PACKAGE_NAME}.{module_name}"
        module_path = ROOT / "custom_components" / "finance_tracker" / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(qualified_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified_name] = module
        spec.loader.exec_module(module)

    return sys.modules[f"{PACKAGE_NAME}.storage"]


storage_module = _load_storage_module()
FinanceTrackerStorage = storage_module.FinanceTrackerStorage


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, relative_path: str) -> str:
        return str(self._root / relative_path)


class _FakeHass:
    def __init__(self, root: Path) -> None:
        self.config = _FakeConfig(root)

    async def async_add_executor_job(self, target, *args):
        return target(*args)


class FinanceTrackerStorageTests(unittest.IsolatedAsyncioTestCase):
    """Exercise durable workflows without a running Home Assistant instance."""

    async def asyncSetUp(self) -> None:
        self._temporary_directory = TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.storage = FinanceTrackerStorage(
            _FakeHass(Path(self._temporary_directory.name))
        )
        await self.storage.async_initialize()

    async def _add_monthly_expense(self, amount: float = 100.0) -> dict:
        return await self.storage.async_add_expense(
            {
                "name": "Electricity",
                "category": "Utilities",
                "recurrence": "monthly",
                "amount": amount,
                "due_day": 15,
                "reminder_days": 3,
            }
        )

    async def test_monthly_generation_preserves_month_overrides(self) -> None:
        await self.storage.async_add_expense(
            {
                "name": "Electricity",
                "category": "Utilities",
                "recurrence": "monthly",
                "amount": 100.0,
                "due_day": 15,
                "month_amount_overrides": {"2": 125.5},
                "month_day_overrides": {"2": 20},
            }
        )

        generated = await self.storage.async_generate_year(2027)
        plan = await self.storage.async_get_year_plan(2027)
        february = next(item for item in plan["items"] if item["month_key"] == "2027-02")

        self.assertEqual(generated["created_entries"], 12)
        self.assertEqual(plan["item_count"], 12)
        self.assertEqual(february["scheduled_amount"], 125.5)
        self.assertEqual(february["due_date"], "2027-02-20")

    async def test_partial_payment_full_payment_and_undo_recalculate_balance(self) -> None:
        await self._add_monthly_expense()
        await self.storage.async_generate_year(2027)
        january = await self.storage.async_get_current_month(month_key="2027-01")
        entry_id = january["entries"][0]["entry_id"]

        partial = await self.storage.async_mark_partial(
            entry_id, 40.0, "2027-01-10", "First payment"
        )
        final = await self.storage.async_mark_paid(
            entry_id, 60.0, "2027-01-12", "Final payment"
        )
        undone = await self.storage.async_undo_payment(final["payment_id"])

        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["remaining_amount"], 60.0)
        self.assertEqual(final["status"], "paid")
        self.assertEqual(final["remaining_amount"], 0.0)
        self.assertEqual(undone["entry"]["status"], "partial")
        self.assertEqual(undone["entry"]["actual_paid_amount"], 40.0)
        self.assertEqual(undone["entry"]["remaining_amount"], 60.0)

    async def test_copy_year_creates_reviewable_draft_with_same_schedule(self) -> None:
        await self._add_monthly_expense(amount=89.99)
        await self.storage.async_generate_year(2027)
        await self.storage.async_activate_year(2027)

        copied = await self.storage.async_copy_year(2027, 2028)
        source = await self.storage.async_get_year_plan(2027)
        target = await self.storage.async_get_year_plan(2028)

        self.assertEqual(copied["created_entries"], 12)
        self.assertEqual(target["plan"]["status"], "draft")
        self.assertEqual(target["plan"]["source_year"], 2027)
        self.assertEqual(target["item_count"], source["item_count"])
        self.assertEqual(
            [item["scheduled_amount"] for item in target["items"]],
            [item["scheduled_amount"] for item in source["items"]],
        )

    async def test_expense_catalog_supports_edit_and_archive(self) -> None:
        created = await self._add_monthly_expense()

        await self.storage.async_update_expense(
            created["template_id"],
            {
                "name": "Power bill",
                "amount": 115.25,
                "due_day": None,
                "notes": "Updated from the panel",
            },
        )
        updated_catalog = await self.storage.async_list_expenses()
        updated = updated_catalog["expenses"][0]

        self.assertEqual(updated["name"], "Power bill")
        self.assertEqual(updated["default_amount"], 115.25)
        self.assertIsNone(updated["due_day"])
        self.assertEqual(updated["notes"], "Updated from the panel")

        await self.storage.async_archive_expense(created["template_id"])
        active_catalog = await self.storage.async_list_expenses(active_only=True)
        complete_catalog = await self.storage.async_list_expenses()

        self.assertEqual(active_catalog["count"], 0)
        self.assertEqual(complete_catalog["count"], 1)
        self.assertFalse(complete_catalog["expenses"][0]["is_active"])

    async def test_year_plan_adjustment_updates_plan_and_month_ledger(self) -> None:
        await self._add_monthly_expense()
        await self.storage.async_generate_year(2027)
        january = await self.storage.async_get_current_month(month_key="2027-01")
        entry_id = january["entries"][0]["entry_id"]

        await self.storage.async_update_month_entry(
            entry_id,
            {
                "scheduled_amount": 132.75,
                "due_date": "2027-01-21",
                "notes": "Adjusted during year review",
            },
        )
        plan = await self.storage.async_get_year_plan(2027, month=1)
        ledger = await self.storage.async_get_current_month(month_key="2027-01")

        self.assertEqual(plan["items"][0]["scheduled_amount"], 132.75)
        self.assertEqual(plan["items"][0]["due_date"], "2027-01-21")
        self.assertEqual(ledger["entries"][0]["remaining_amount"], 132.75)
        self.assertEqual(ledger["entries"][0]["notes"], "Adjusted during year review")

    async def test_cleanup_tools_delete_year_and_clear_reminder_log(self) -> None:
        await self._add_monthly_expense()
        await self.storage.async_generate_year(2027)
        january = await self.storage.async_get_current_month(month_key="2027-01")
        entry_id = january["entries"][0]["entry_id"]
        await self.storage.async_mark_paid(entry_id, 100.0, "2027-01-10", None)
        await self.storage.async_log_notification(
            entry_id,
            "due_today",
            "due_today:2027-01-10:test",
            "persistent_notification.create",
            {"message": "test"},
        )

        cleared = await self.storage.async_clear_reminder_log()
        deleted = await self.storage.async_delete_year_plan(2027)
        current = await self.storage.async_get_current_month(month_key="2027-01")
        catalog = await self.storage.async_list_expenses()

        self.assertEqual(cleared["deleted_notifications"], 1)
        self.assertEqual(deleted["deleted_entries"], 12)
        self.assertEqual(deleted["deleted_payments"], 1)
        self.assertEqual(current["entry_count"], 0)
        self.assertEqual(catalog["count"], 1)

    async def test_cleanup_tools_delete_month_and_reset_database(self) -> None:
        await self._add_monthly_expense()
        await self.storage.async_generate_year(2027)
        january = await self.storage.async_get_current_month(month_key="2027-01")
        entry_id = january["entries"][0]["entry_id"]
        payment = await self.storage.async_mark_paid(entry_id, 100.0, "2027-01-10", None)
        paid_january = await self.storage.async_get_current_month(month_key="2027-01")

        deleted_month = await self.storage.async_delete_month("2027-01")
        current = await self.storage.async_get_current_month(month_key="2027-01")
        reset = await self.storage.async_reset_database()
        catalog = await self.storage.async_list_expenses()

        self.assertEqual(paid_january["entries"][0]["latest_payment_id"], payment["payment_id"])
        self.assertEqual(deleted_month["deleted_entries"], 1)
        self.assertEqual(deleted_month["deleted_payments"], 1)
        self.assertEqual(current["entry_count"], 0)
        self.assertGreaterEqual(reset["deleted_counts"]["expense_templates"], 1)
        self.assertEqual(catalog["count"], 0)

    async def test_current_month_filters_by_status_and_category(self) -> None:
        await self._add_monthly_expense()
        await self.storage.async_add_expense(
            {
                "name": "Rent",
                "category": "Housing",
                "recurrence": "monthly",
                "amount": 500.0,
                "due_day": 1,
            }
        )
        await self.storage.async_generate_year(2027)
        january = await self.storage.async_get_current_month(month_key="2027-01")
        utility = next(
            entry for entry in january["entries"] if entry["category"] == "Utilities"
        )
        await self.storage.async_mark_partial(
            utility["entry_id"], 25.0, "2027-01-05", None
        )

        filtered = await self.storage.async_get_current_month(
            month_key="2027-01", status="partial", category="Utilities"
        )

        self.assertEqual(filtered["entry_count"], 1)
        self.assertEqual(filtered["entries"][0]["name"], "Electricity")
        self.assertEqual(filtered["summary"]["status_counts"]["partial"], 1)

    async def test_current_month_keeps_unpaid_entries_above_paid_entries(self) -> None:
        await self._add_monthly_expense()
        await self.storage.async_add_expense(
            {
                "name": "Rent",
                "category": "Housing",
                "recurrence": "monthly",
                "amount": 500.0,
                "due_day": 1,
            }
        )
        await self.storage.async_generate_year(2027)
        january = await self.storage.async_get_current_month(month_key="2027-01")
        first_entry = january["entries"][0]

        await self.storage.async_mark_paid(
            first_entry["entry_id"], first_entry["remaining_amount"], "2027-01-05", None
        )
        reordered = await self.storage.async_get_current_month(month_key="2027-01")

        self.assertEqual(reordered["entries"][0]["status"], "pending")
        self.assertEqual(reordered["entries"][1]["status"], "paid")
        self.assertEqual(reordered["entries"][1]["entry_id"], first_entry["entry_id"])

    async def test_history_returns_monthly_category_and_payment_rollups(self) -> None:
        await self._add_monthly_expense()
        await self.storage.async_generate_year(2027)
        january = await self.storage.async_get_current_month(month_key="2027-01")
        entry_id = january["entries"][0]["entry_id"]
        await self.storage.async_mark_partial(
            entry_id, 40.0, "2027-01-10", "History test"
        )

        history = await self.storage.async_get_history(2027)
        january_history = history["monthly"][0]
        utilities = history["summary"]["category_totals"][0]

        self.assertEqual(history["entry_count"], 12)
        self.assertEqual(history["summary"]["scheduled_total"], 1200.0)
        self.assertEqual(history["summary"]["actual_paid_total"], 40.0)
        self.assertEqual(january_history["entry_count"], 1)
        self.assertEqual(january_history["summary"]["actual_paid_total"], 40.0)
        self.assertEqual(utilities["category"], "Utilities")
        self.assertEqual(len(history["payments"]), 1)
        self.assertEqual(history["payments"][0]["note"], "History test")

    async def test_settings_persist_and_reminders_are_deduplicated_daily(self) -> None:
        settings = await self.storage.async_update_settings(
            {
                "currency": "usd",
                "reminders_enabled": True,
                "notification_service": "notify.mobile_app_phone",
                "scan_interval_minutes": 30,
            }
        )
        self.assertEqual(settings["currency"], "USD")
        self.assertEqual(settings["scan_interval_minutes"], 30)

        await self._add_monthly_expense()
        await self.storage.async_generate_year(2027)
        candidates = await self.storage.async_get_reminder_candidates("2027-01-14")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reminder_type"], "upcoming")
        self.assertEqual(candidates[0]["days_until_due"], 1)

        candidate = candidates[0]
        await self.storage.async_log_notification(
            candidate["entry_id"],
            candidate["reminder_type"],
            candidate["dedupe_key"],
            settings["notification_service"],
            {"message": "test"},
        )
        repeated = await self.storage.async_get_reminder_candidates("2027-01-14")
        next_day = await self.storage.async_get_reminder_candidates("2027-01-15")

        self.assertEqual(repeated, [])
        self.assertEqual(len(next_day), 1)
        self.assertEqual(next_day[0]["reminder_type"], "due")

    async def test_database_initialization_records_schema_version(self) -> None:
        diagnostics = await self.storage.async_run_diagnostics()
        with closing(sqlite3.connect(self.storage._db_path)) as conn:
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(user_version, 1)
        self.assertEqual(diagnostics["schema_version"], 1)

    async def test_schema_adoption_preserves_existing_records(self) -> None:
        created = await self._add_monthly_expense()
        with closing(sqlite3.connect(self.storage._db_path)) as conn:
            conn.execute("PRAGMA user_version = 0")
            conn.commit()

        await self.storage.async_initialize()
        catalog = await self.storage.async_list_expenses()
        diagnostics = await self.storage.async_run_diagnostics()

        self.assertEqual(catalog["count"], 1)
        self.assertEqual(catalog["expenses"][0]["template_id"], created["template_id"])
        self.assertEqual(diagnostics["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
