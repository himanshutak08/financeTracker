"""Reminder scheduling and Home Assistant notification delivery."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.util import dt as dt_util

from .storage import FinanceTrackerStorage

LOGGER = logging.getLogger(__name__)


class FinanceTrackerReminderManager:
    """Scan finance entries and deliver deduplicated reminders."""

    def __init__(self, hass: HomeAssistant, storage: FinanceTrackerStorage) -> None:
        self._hass = hass
        self._storage = storage
        self._cancel_interval = None
        self._cancel_daily = None
        self._run_lock = asyncio.Lock()

    async def async_setup(self) -> None:
        """Start the periodic reminder scan."""
        await self.async_reschedule()
        self._hass.async_create_task(self.async_run())

    async def async_reschedule(self) -> None:
        """Apply the configured scan interval."""
        if self._cancel_interval is not None:
            self._cancel_interval()
        if self._cancel_daily is not None:
            self._cancel_daily()
        settings = await self._storage.async_get_settings()
        self._cancel_interval = async_track_time_interval(
            self._hass,
            self.async_run,
            timedelta(minutes=settings["scan_interval_minutes"]),
        )
        hour, minute = (
            int(part)
            for part in settings.get("digest_time", "22:00").split(":")
        )
        self._cancel_daily = async_track_time_change(
            self._hass,
            self.async_run,
            hour=hour,
            minute=minute,
            second=0,
        )

    async def async_run(
        self, now: Any = None, *, force: bool = False
    ) -> dict[str, Any]:
        """Serialize scheduled and manual reminder scans."""
        async with self._run_lock:
            return await self._async_run(now, force=force)

    async def _async_run(
        self, now: Any = None, *, force: bool = False
    ) -> dict[str, Any]:
        """Deliver grouped daily reminders when the configured time is reached."""
        settings = await self._storage.async_get_settings()
        if not settings["reminders_enabled"]:
            return {"enabled": False, "candidates": 0, "digests": 0, "sent": 0, "failed": 0}

        effective_now = dt_util.as_local(now) if now is not None else dt_util.now()
        digest_time = settings.get("digest_time", "22:00")
        if not force and effective_now.strftime("%H:%M") < digest_time:
            return {
                "enabled": True,
                "waiting": True,
                "digest_time": digest_time,
                "candidates": 0,
                "digests": 0,
                "sent": 0,
                "failed": 0,
            }

        candidates = await self._storage.async_get_reminder_candidates(
            effective_now.date().isoformat()
        )
        groups: dict[str, list[dict[str, Any]]] = {
            "action_required": [],
            "due_tomorrow": [],
            "upcoming": [],
        }
        for candidate in candidates:
            if candidate["days_until_due"] <= 0:
                groups["action_required"].append(candidate)
            elif candidate["days_until_due"] == 1:
                groups["due_tomorrow"].append(candidate)
            else:
                groups["upcoming"].append(candidate)

        service_paths = [settings["notification_service"]]
        mobile_service = settings.get("mobile_notification_service", "")
        if mobile_service and mobile_service not in service_paths:
            service_paths.append(mobile_service)
        required_service = mobile_service or settings["notification_service"]
        sent = 0
        failed = 0
        digest_count = 0
        for group_name, group_candidates in groups.items():
            if not group_candidates:
                continue
            digest_count += 1
            payload = self._digest_payload(
                group_name, group_candidates, settings["currency"]
            )
            delivered = []
            for service_path in service_paths:
                domain, service = service_path.split(".", 1)
                try:
                    await self._hass.services.async_call(
                        domain, service, payload, blocking=True
                    )
                    delivered.append(service_path)
                except Exception:
                    LOGGER.exception(
                        "Failed to send %s reminder digest through %s",
                        group_name, service_path,
                    )
            if required_service not in delivered:
                failed += 1
                continue
            for candidate in group_candidates:
                await self._storage.async_log_notification(
                    candidate["entry_id"],
                    candidate["reminder_type"],
                    candidate["dedupe_key"],
                    ",".join(delivered),
                    payload,
                )
            sent += 1

        return {
            "enabled": True,
            "candidates": len(candidates),
            "digests": digest_count,
            "sent": sent,
            "failed": failed,
        }

    def async_unload(self) -> None:
        """Stop periodic scans."""
        if self._cancel_interval is not None:
            self._cancel_interval()
            self._cancel_interval = None
        if self._cancel_daily is not None:
            self._cancel_daily()
            self._cancel_daily = None

    @staticmethod
    def _digest_payload(
        group_name: str, candidates: list[dict[str, Any]], currency: str
    ) -> dict[str, str]:
        titles = {
            "action_required": "Finance Tracker: Action required",
            "due_tomorrow": "Finance Tracker: Due tomorrow",
            "upcoming": "Finance Tracker: Upcoming",
        }
        total = sum(candidate["remaining_amount"] for candidate in candidates)
        names = ", ".join(
            f"{candidate['name']} ({candidate['due_date']})"
            for candidate in candidates
        )
        message = (
            f"{len(candidates)} expense(s) · {currency} {total:.2f}\n"
            f"{names}"
        )
        return {"title": titles[group_name], "message": message}
