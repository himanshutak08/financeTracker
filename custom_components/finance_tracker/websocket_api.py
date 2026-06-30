"""Websocket commands for the Finance Tracker panel."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .const import DOMAIN, STORAGE_KEY
from .importer import parse_expense_file
from .storage import FinanceTrackerStorage


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register websocket commands used by the panel."""
    websocket_api.async_register_command(hass, ws_list_expenses)
    websocket_api.async_register_command(hass, ws_get_current_month)
    websocket_api.async_register_command(hass, ws_get_year_plan)
    websocket_api.async_register_command(hass, ws_get_history)
    websocket_api.async_register_command(hass, ws_get_settings)
    websocket_api.async_register_command(hass, ws_import_expenses_file)
    websocket_api.async_register_command(hass, ws_delete_year_plan)
    websocket_api.async_register_command(hass, ws_delete_month)
    websocket_api.async_register_command(hass, ws_reset_database)
    websocket_api.async_register_command(hass, ws_clear_reminder_log)


def _storage(hass: HomeAssistant) -> FinanceTrackerStorage:
    return hass.data[DOMAIN][STORAGE_KEY]


@websocket_api.websocket_command(
    {
        vol.Required("type"): "finance_tracker/list_expenses",
        vol.Optional("active_only", default=False): bool,
        vol.Optional("category"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_list_expenses(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return expense master rows for the panel."""
    try:
        result = await _storage(hass).async_list_expenses(
            active_only=msg.get("active_only", False),
            category=msg.get("category"),
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(websocket_api.result_message(msg["id"], result))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "finance_tracker/get_current_month",
        vol.Optional("month_key"): str,
        vol.Optional("status"): str,
        vol.Optional("category"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_get_current_month(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return month ledger rows and summary totals."""
    try:
        result = await _storage(hass).async_get_current_month(
            month_key=msg.get("month_key"),
            status=msg.get("status"),
            category=msg.get("category"),
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(websocket_api.result_message(msg["id"], result))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "finance_tracker/get_year_plan",
        vol.Required("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100)),
        vol.Optional("month"): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_get_year_plan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return year plan details for planning views."""
    try:
        result = await _storage(hass).async_get_year_plan(
            plan_year=msg["year"],
            month=msg.get("month"),
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(websocket_api.result_message(msg["id"], result))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "finance_tracker/get_history",
        vol.Required("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_get_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return yearly reporting data for the History panel."""
    try:
        result = await _storage(hass).async_get_history(msg["year"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(websocket_api.result_message(msg["id"], result))


@websocket_api.websocket_command(
    {vol.Required("type"): "finance_tracker/get_settings"}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_get_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return application and reminder settings."""
    try:
        result = await _storage(hass).async_get_settings()
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(websocket_api.result_message(msg["id"], result))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "finance_tracker/import_expenses_file",
        vol.Required("filename"): str,
        vol.Required("content"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_import_expenses_file(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Import expense definitions from an uploaded file."""
    try:
        rows = parse_expense_file(msg["filename"], msg["content"])
        imported = []
        storage = _storage(hass)
        for row in rows:
            imported.append(await storage.async_add_expense(row))
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(
        websocket_api.result_message(
            msg["id"],
            {
                "filename": msg["filename"],
                "imported_count": len(imported),
                "expenses": imported,
            },
        )
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "finance_tracker/delete_year_plan",
        vol.Required("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_year_plan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one generated year plan and its ledger rows."""
    try:
        result = await _storage(hass).async_delete_year_plan(msg["year"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(websocket_api.result_message(msg["id"], result))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "finance_tracker/delete_month",
        vol.Required("month_key"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_month(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one generated month ledger."""
    try:
        result = await _storage(hass).async_delete_month(msg["month_key"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(websocket_api.result_message(msg["id"], result))


@websocket_api.websocket_command(
    {vol.Required("type"): "finance_tracker/reset_database"}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_reset_database(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete all Finance Tracker user data while keeping the schema."""
    try:
        result = await _storage(hass).async_reset_database()
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(websocket_api.result_message(msg["id"], result))


@websocket_api.websocket_command(
    {vol.Required("type"): "finance_tracker/clear_reminder_log"}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_clear_reminder_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Clear reminder dedupe history."""
    try:
        result = await _storage(hass).async_clear_reminder_log()
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
        return

    connection.send_message(websocket_api.result_message(msg["id"], result))
