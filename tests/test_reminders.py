"""Tests for grouped Finance Tracker reminder delivery."""

from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "custom_components.finance_tracker"


def _load_reminders_module():
    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    event = types.ModuleType("homeassistant.helpers.event")
    util = types.ModuleType("homeassistant.util")
    dt_module = types.ModuleType("homeassistant.util.dt")

    core.HomeAssistant = object
    event.async_track_time_interval = lambda *args: lambda: None
    event.async_track_time_change = lambda *args, **kwargs: lambda: None
    dt_module.as_local = lambda value: value
    dt_module.now = lambda: datetime(2027, 1, 14, 22, 0)
    util.dt = dt_module
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.event"] = event
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt_module

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT / "custom_components" / "finance_tracker")]
    sys.modules[PACKAGE_NAME] = package
    storage = types.ModuleType(f"{PACKAGE_NAME}.storage")
    storage.FinanceTrackerStorage = object
    sys.modules[f"{PACKAGE_NAME}.storage"] = storage

    qualified_name = f"{PACKAGE_NAME}.reminders"
    path = ROOT / "custom_components" / "finance_tracker" / "reminders.py"
    spec = importlib.util.spec_from_file_location(qualified_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module


reminders_module = _load_reminders_module()
FinanceTrackerReminderManager = reminders_module.FinanceTrackerReminderManager


class _Services:
    def __init__(self, failing_service: str | None = None) -> None:
        self.calls = []
        self.failing_service = failing_service

    async def async_call(self, domain, service, payload, blocking=False):
        path = f"{domain}.{service}"
        self.calls.append((path, payload))
        if path == self.failing_service:
            raise RuntimeError("delivery failed")


class _Hass:
    def __init__(self, failing_service: str | None = None) -> None:
        self.services = _Services(failing_service)


class _Storage:
    def __init__(self, candidates) -> None:
        self.candidates = candidates
        self.logged = []
        self.settings = {
            "currency": "INR",
            "reminders_enabled": True,
            "notification_service": "persistent_notification.create",
            "mobile_notification_service": "notify.mobile_app_phone",
            "scan_interval_minutes": 60,
            "digest_time": "22:00",
        }

    async def async_get_settings(self):
        return self.settings

    async def async_get_reminder_candidates(self, today=None):
        return self.candidates

    async def async_log_notification(self, *args):
        self.logged.append(args)


def _candidate(name, days, reminder_type):
    return {
        "entry_id": name.lower().replace(" ", "-"),
        "name": name,
        "due_date": f"2027-01-{14 + days:02d}",
        "remaining_amount": 100.0,
        "days_until_due": days,
        "reminder_type": reminder_type,
        "dedupe_key": f"{name}:{reminder_type}:2027-01-14",
    }


class ReminderManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_until_configured_digest_time(self):
        storage = _Storage([_candidate("Tomorrow", 1, "upcoming")])
        manager = FinanceTrackerReminderManager(_Hass(), storage)

        result = await manager.async_run(datetime(2027, 1, 14, 21, 59))

        self.assertTrue(result["waiting"])
        self.assertEqual(result["sent"], 0)

    async def test_groups_all_names_into_three_daily_digests(self):
        candidates = [
            _candidate("Overdue Rent", -1, "overdue"),
            _candidate("Due Today", 0, "due"),
            _candidate("Tomorrow EMI", 1, "upcoming"),
            _candidate("Upcoming Internet", 3, "upcoming"),
        ]
        storage = _Storage(candidates)
        hass = _Hass()
        manager = FinanceTrackerReminderManager(hass, storage)

        result = await manager.async_run(datetime(2027, 1, 14, 22, 0))

        self.assertEqual(result["digests"], 3)
        self.assertEqual(result["sent"], 3)
        self.assertEqual(len(storage.logged), 4)
        phone_payloads = [payload for path, payload in hass.services.calls if path == "notify.mobile_app_phone"]
        self.assertEqual(len(phone_payloads), 3)
        combined = " ".join(payload["message"] for payload in phone_payloads)
        for candidate in candidates:
            self.assertIn(candidate["name"], combined)

    async def test_phone_failure_does_not_mark_digest_delivered(self):
        storage = _Storage([_candidate("Tomorrow EMI", 1, "upcoming")])
        manager = FinanceTrackerReminderManager(
            _Hass("notify.mobile_app_phone"), storage
        )

        result = await manager.async_run(force=True)

        self.assertEqual(result["failed"], 1)
        self.assertEqual(storage.logged, [])


if __name__ == "__main__":
    unittest.main()
