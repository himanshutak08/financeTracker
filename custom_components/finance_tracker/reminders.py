"""Reminder scheduling and Home Assistant notification delivery."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .storage import FinanceTrackerStorage

LOGGER = logging.getLogger(__name__)


class FinanceTrackerReminderManager:
    """Scan finance entries and deliver deduplicated reminders."""

    def __init__(self, hass: HomeAssistant, storage: FinanceTrackerStorage) -> None:
        self._hass = hass
        self._storage = storage
        self._cancel_interval = None

    async def async_setup(self) -> None:
        """Start the periodic reminder scan."""
        await self.async_reschedule()
        self._hass.async_create_task(self.async_run())

    async def async_reschedule(self) -> None:
        """Apply the configured scan interval."""
        if self._cancel_interval is not None:
            self._cancel_interval()
        settings = await self._storage.async_get_settings()
        self._cancel_interval = async_track_time_interval(
            self._hass,
            self.async_run,
            timedelta(minutes=settings["scan_interval_minutes"]),
        )

    async def async_run(self, now: Any = None) -> dict[str, Any]:
        """Deliver all currently eligible reminders."""
        settings = await self._storage.async_get_settings()
        if not settings["reminders_enabled"]:
            return {"enabled": False, "candidates": 0, "sent": 0, "failed": 0}

        candidates = await self._storage.async_get_reminder_candidates()
        service_path = settings["notification_service"]
        domain, service = service_path.split(".", 1)
        sent = 0
        failed = 0
        for candidate in candidates:
            message = self._message(candidate, settings["currency"])
            payload = {"title": "Finance Tracker", "message": message}
            try:
                await self._hass.services.async_call(
                    domain, service, payload, blocking=True
                )
            except Exception:
                failed += 1
                LOGGER.exception("Failed to send reminder for %s", candidate["entry_id"])
                continue
            await self._storage.async_log_notification(
                candidate["entry_id"],
                candidate["reminder_type"],
                candidate["dedupe_key"],
                service_path,
                payload,
            )
            sent += 1

        return {
            "enabled": True,
            "candidates": len(candidates),
            "sent": sent,
            "failed": failed,
        }

    def async_unload(self) -> None:
        """Stop periodic scans."""
        if self._cancel_interval is not None:
            self._cancel_interval()
            self._cancel_interval = None

    @staticmethod
    def _message(candidate: dict[str, Any], currency: str) -> str:
        amount = f"{currency} {candidate['remaining_amount']:.2f}"
        if candidate["reminder_type"] == "overdue":
            timing = f"was due {abs(candidate['days_until_due'])} day(s) ago"
        elif candidate["reminder_type"] == "due":
            timing = "is due today"
        else:
            timing = f"is due in {candidate['days_until_due']} day(s)"
        return f"{candidate['name']} ({amount}) {timing} on {candidate['due_date']}."
