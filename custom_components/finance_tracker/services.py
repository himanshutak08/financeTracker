"""Service registration for Finance Tracker."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import (
    DOMAIN,
    SERVICE_ADD_EXPENSE,
    SERVICE_GENERATE_YEAR,
    SERVICE_MARK_PAID,
    SERVICE_UPDATE_EXPENSE,
)
from .storage import FinanceTrackerStorage

ADD_EXPENSE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Required("category"): str,
        vol.Required("recurrence"): str,
        vol.Required("amount"): vol.Coerce(float),
        vol.Optional("due_day"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=31))),
        vol.Optional("due_date"): str,
        vol.Optional("start_month"): vol.Any(str, int),
        vol.Optional("end_month"): vol.Any(str, int),
        vol.Optional("icon"): str,
        vol.Optional("notes"): str,
        vol.Optional("reminder_days", default=3): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
        vol.Optional("custom_months"): vol.Any(str, [vol.Coerce(int)]),
        vol.Optional("month_amount_overrides"): {str: vol.Coerce(float)},
        vol.Optional("month_day_overrides"): {
            str: vol.All(vol.Coerce(int), vol.Range(min=1, max=31))
        },
    }
)

UPDATE_EXPENSE_SCHEMA = vol.Schema(
    {
        vol.Required("template_id"): str,
        vol.Optional("name"): str,
        vol.Optional("category"): str,
        vol.Optional("recurrence"): str,
        vol.Optional("amount"): vol.Coerce(float),
        vol.Optional("due_day"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=31))),
        vol.Optional("due_date"): str,
        vol.Optional("start_month"): vol.Any(str, int),
        vol.Optional("end_month"): vol.Any(str, int),
        vol.Optional("icon"): vol.Any(None, str),
        vol.Optional("notes"): vol.Any(None, str),
        vol.Optional("reminder_days"): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
        vol.Optional("is_active"): bool,
        vol.Optional("custom_months"): vol.Any(str, [vol.Coerce(int)]),
        vol.Optional("month_amount_overrides"): {str: vol.Coerce(float)},
        vol.Optional("month_day_overrides"): {
            str: vol.All(vol.Coerce(int), vol.Range(min=1, max=31))
        },
    }
)

GENERATE_YEAR_SCHEMA = vol.Schema(
    {vol.Required("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100))}
)

MARK_PAID_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): str,
        vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
        vol.Optional("paid_date"): str,
        vol.Optional("note"): str,
    }
)


class FinanceTrackerServiceManager:
    """Register and unload finance tracker services."""

    def __init__(self, hass: HomeAssistant, storage: FinanceTrackerStorage) -> None:
        self._hass = hass
        self._storage = storage

    async def async_setup(self) -> None:
        """Register service handlers."""
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_ADD_EXPENSE,
            self._handle_add_expense,
            schema=ADD_EXPENSE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_UPDATE_EXPENSE,
            self._handle_update_expense,
            schema=UPDATE_EXPENSE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_GENERATE_YEAR,
            self._handle_generate_year,
            schema=GENERATE_YEAR_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_PAID,
            self._handle_mark_paid,
            schema=MARK_PAID_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    def async_on_unload(self) -> None:
        """Remove registered services."""
        for service_name in (
            SERVICE_ADD_EXPENSE,
            SERVICE_UPDATE_EXPENSE,
            SERVICE_GENERATE_YEAR,
            SERVICE_MARK_PAID,
        ):
            self._hass.services.async_remove(DOMAIN, service_name)

    async def _handle_add_expense(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_add_expense(call.data)

    async def _handle_update_expense(self, call: ServiceCall) -> dict[str, Any]:
        template_id = call.data["template_id"]
        changes = {key: value for key, value in call.data.items() if key != "template_id"}
        return await self._storage.async_update_expense(template_id, changes)

    async def _handle_generate_year(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_generate_year(call.data["year"])

    async def _handle_mark_paid(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_mark_paid(
            call.data["entry_id"],
            call.data["amount"],
            call.data.get("paid_date"),
            call.data.get("note"),
        )
