"""Service registration for Finance Tracker."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import (
    DOMAIN,
    SERVICE_ACTIVATE_YEAR,
    SERVICE_ADD_EXPENSE,
    SERVICE_ARCHIVE_EXPENSE,
    SERVICE_DELETE_EXPENSES,
    SERVICE_COPY_YEAR,
    SERVICE_GENERATE_YEAR,
    SERVICE_GET_CURRENT_MONTH,
    SERVICE_GET_HISTORY,
    SERVICE_GET_SETTINGS,
    SERVICE_GET_YEAR_PLAN,
    SERVICE_IMPORT_EXPENSES_FILE,
    SERVICE_LIST_EXPENSES,
    SERVICE_MARK_PAID,
    SERVICE_MARK_PARTIAL,
    SERVICE_RUN_DIAGNOSTICS,
    SERVICE_RUN_REMINDERS,
    SERVICE_UNDO_PAYMENT,
    SERVICE_UPDATE_EXPENSE,
    SERVICE_UPDATE_MONTH_ENTRY,
    SERVICE_UPDATE_SETTINGS,
    REMINDER_MANAGER_KEY,
)
from .storage import FinanceTrackerStorage
from .importer import parse_expense_file

ADD_EXPENSE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Required("category"): str,
        vol.Required("recurrence"): str,
        vol.Required("amount"): vol.Coerce(float),
        vol.Optional("due_day"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=31))),
        vol.Optional("due_date"): str,
        vol.Optional("start_month"): vol.Any(None, str, int),
        vol.Optional("end_month"): vol.Any(None, str, int),
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

IMPORT_EXPENSES_FILE_SCHEMA = vol.Schema(
    {
        vol.Required("filename"): str,
        vol.Required("content"): str,
    }
)

ARCHIVE_EXPENSE_SCHEMA = vol.Schema({vol.Required("template_id"): str})
DELETE_EXPENSES_SCHEMA = vol.Schema({vol.Required("template_ids"): [str]})

COPY_YEAR_SCHEMA = vol.Schema(
    {
        vol.Required("source_year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100)),
        vol.Required("target_year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100)),
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
        vol.Optional("start_month"): vol.Any(None, str, int),
        vol.Optional("end_month"): vol.Any(None, str, int),
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

ACTIVATE_YEAR_SCHEMA = vol.Schema(
    {vol.Required("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100))}
)

LIST_EXPENSES_SCHEMA = vol.Schema(
    {
        vol.Optional("active_only", default=False): bool,
        vol.Optional("category"): str,
    }
)

GET_CURRENT_MONTH_SCHEMA = vol.Schema(
    {
        vol.Optional("month_key"): str,
        vol.Optional("status"): str,
        vol.Optional("category"): str,
    }
)

GET_YEAR_PLAN_SCHEMA = vol.Schema(
    {
        vol.Required("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100)),
        vol.Optional("month"): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
    }
)

GET_HISTORY_SCHEMA = vol.Schema(
    {vol.Required("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100))}
)

GET_SETTINGS_SCHEMA = vol.Schema({})
UPDATE_SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Optional("currency"): str,
        vol.Optional("reminders_enabled"): bool,
        vol.Optional("notification_service"): str,
        vol.Optional("mobile_notification_service"): str,
        vol.Optional("scan_interval_minutes"): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=1440)
        ),
    }
)
RUN_REMINDERS_SCHEMA = vol.Schema({})

RUN_DIAGNOSTICS_SCHEMA = vol.Schema({})

MARK_PAID_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): str,
        vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
        vol.Optional("paid_date"): str,
        vol.Optional("note"): str,
    }
)

MARK_PARTIAL_SCHEMA = MARK_PAID_SCHEMA

UPDATE_MONTH_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): str,
        vol.Optional("name"): str,
        vol.Optional("category"): str,
        vol.Optional("icon"): vol.Any(None, str),
        vol.Optional("notes"): vol.Any(None, str),
        vol.Optional("due_date"): vol.Any(None, str),
        vol.Optional("scheduled_amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)

UNDO_PAYMENT_SCHEMA = vol.Schema({vol.Required("payment_id"): str})


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
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_IMPORT_EXPENSES_FILE,
            self._handle_import_expenses_file,
            schema=IMPORT_EXPENSES_FILE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_ARCHIVE_EXPENSE,
            self._handle_archive_expense,
            schema=ARCHIVE_EXPENSE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_DELETE_EXPENSES,
            self._handle_delete_expenses,
            schema=DELETE_EXPENSES_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_COPY_YEAR,
            self._handle_copy_year,
            schema=COPY_YEAR_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_UPDATE_EXPENSE,
            self._handle_update_expense,
            schema=UPDATE_EXPENSE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_GENERATE_YEAR,
            self._handle_generate_year,
            schema=GENERATE_YEAR_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_ACTIVATE_YEAR,
            self._handle_activate_year,
            schema=ACTIVATE_YEAR_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_LIST_EXPENSES,
            self._handle_list_expenses,
            schema=LIST_EXPENSES_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_GET_CURRENT_MONTH,
            self._handle_get_current_month,
            schema=GET_CURRENT_MONTH_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_GET_YEAR_PLAN,
            self._handle_get_year_plan,
            schema=GET_YEAR_PLAN_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_GET_HISTORY,
            self._handle_get_history,
            schema=GET_HISTORY_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_GET_SETTINGS,
            self._handle_get_settings,
            schema=GET_SETTINGS_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_UPDATE_SETTINGS,
            self._handle_update_settings,
            schema=UPDATE_SETTINGS_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_RUN_REMINDERS,
            self._handle_run_reminders,
            schema=RUN_REMINDERS_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_RUN_DIAGNOSTICS,
            self._handle_run_diagnostics,
            schema=RUN_DIAGNOSTICS_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_PAID,
            self._handle_mark_paid,
            schema=MARK_PAID_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_PARTIAL,
            self._handle_mark_partial,
            schema=MARK_PARTIAL_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_UPDATE_MONTH_ENTRY,
            self._handle_update_month_entry,
            schema=UPDATE_MONTH_ENTRY_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        self._hass.services.async_register(
            DOMAIN,
            SERVICE_UNDO_PAYMENT,
            self._handle_undo_payment,
            schema=UNDO_PAYMENT_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    def async_on_unload(self) -> None:
        """Remove registered services."""
        for service_name in (
            SERVICE_ADD_EXPENSE,
            SERVICE_IMPORT_EXPENSES_FILE,
            SERVICE_ARCHIVE_EXPENSE,
            SERVICE_DELETE_EXPENSES,
            SERVICE_COPY_YEAR,
            SERVICE_UPDATE_EXPENSE,
            SERVICE_GENERATE_YEAR,
            SERVICE_ACTIVATE_YEAR,
            SERVICE_LIST_EXPENSES,
            SERVICE_GET_CURRENT_MONTH,
            SERVICE_GET_YEAR_PLAN,
            SERVICE_GET_HISTORY,
            SERVICE_GET_SETTINGS,
            SERVICE_UPDATE_SETTINGS,
            SERVICE_RUN_REMINDERS,
            SERVICE_RUN_DIAGNOSTICS,
            SERVICE_MARK_PAID,
            SERVICE_MARK_PARTIAL,
            SERVICE_UPDATE_MONTH_ENTRY,
            SERVICE_UNDO_PAYMENT,
        ):
            self._hass.services.async_remove(DOMAIN, service_name)

    async def _handle_add_expense(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_add_expense(call.data)

    async def _handle_import_expenses_file(
        self, call: ServiceCall
    ) -> dict[str, Any]:
        rows = parse_expense_file(call.data["filename"], call.data["content"])
        imported = []
        for row in rows:
            imported.append(await self._storage.async_add_expense(row))
        return {
            "filename": call.data["filename"],
            "imported_count": len(imported),
            "expenses": imported,
        }

    async def _handle_archive_expense(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_archive_expense(call.data["template_id"])

    async def _handle_delete_expenses(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_delete_expenses(call.data["template_ids"])

    async def _handle_copy_year(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_copy_year(
            call.data["source_year"],
            call.data["target_year"],
        )

    async def _handle_update_expense(self, call: ServiceCall) -> dict[str, Any]:
        template_id = call.data["template_id"]
        changes = {key: value for key, value in call.data.items() if key != "template_id"}
        return await self._storage.async_update_expense(template_id, changes)

    async def _handle_generate_year(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_generate_year(call.data["year"])

    async def _handle_activate_year(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_activate_year(call.data["year"])

    async def _handle_list_expenses(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_list_expenses(
            active_only=call.data.get("active_only", False),
            category=call.data.get("category"),
        )

    async def _handle_get_current_month(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_get_current_month(
            month_key=call.data.get("month_key"),
            status=call.data.get("status"),
            category=call.data.get("category"),
        )

    async def _handle_get_year_plan(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_get_year_plan(
            plan_year=call.data["year"],
            month=call.data.get("month"),
        )

    async def _handle_get_history(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_get_history(call.data["year"])

    async def _handle_get_settings(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_get_settings()

    async def _handle_update_settings(self, call: ServiceCall) -> dict[str, Any]:
        result = await self._storage.async_update_settings(call.data)
        manager = self._hass.data[DOMAIN].get(REMINDER_MANAGER_KEY)
        if manager is not None:
            await manager.async_reschedule()
        return result

    async def _handle_run_reminders(self, call: ServiceCall) -> dict[str, Any]:
        manager = self._hass.data[DOMAIN].get(REMINDER_MANAGER_KEY)
        if manager is None:
            return {"enabled": False, "candidates": 0, "sent": 0, "failed": 0}
        return await manager.async_run()

    async def _handle_run_diagnostics(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_run_diagnostics()

    async def _handle_mark_paid(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_mark_paid(
            call.data["entry_id"],
            call.data["amount"],
            call.data.get("paid_date"),
            call.data.get("note"),
        )

    async def _handle_mark_partial(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_mark_partial(
            call.data["entry_id"],
            call.data["amount"],
            call.data.get("paid_date"),
            call.data.get("note"),
        )

    async def _handle_update_month_entry(self, call: ServiceCall) -> dict[str, Any]:
        entry_id = call.data["entry_id"]
        changes = {key: value for key, value in call.data.items() if key != "entry_id"}
        return await self._storage.async_update_month_entry(entry_id, changes)

    async def _handle_undo_payment(self, call: ServiceCall) -> dict[str, Any]:
        return await self._storage.async_undo_payment(call.data["payment_id"])
