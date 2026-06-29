"""Temporary diagnostic sensor for Finance Tracker backend validation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STORAGE_KEY
from .storage import FinanceTrackerStorage

SCAN_INTERVAL = timedelta(minutes=1)


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    """Set up the diagnostic sensor for YAML-based development."""
    storage = hass.data[DOMAIN][STORAGE_KEY]
    async_add_entities([FinanceTrackerDiagnosticSensor(storage)], True)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the diagnostic sensor for config-entry installs."""
    storage = hass.data[DOMAIN][STORAGE_KEY]
    async_add_entities([FinanceTrackerDiagnosticSensor(storage)], True)


class FinanceTrackerDiagnosticSensor(SensorEntity):
    """Expose backend readiness without response-only service calls."""

    _attr_has_entity_name = False
    _attr_name = "Finance Tracker Diagnostics"
    _attr_icon = "mdi:stethoscope"

    def __init__(self, storage: FinanceTrackerStorage) -> None:
        self._storage = storage
        self._attr_unique_id = "finance_tracker_diagnostics"

    @property
    def native_value(self) -> str:
        """Return the backend diagnostic status."""
        diagnostics = self._storage.get_cached_diagnostics()
        return str(diagnostics.get("setup_status", "unknown"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic metadata for troubleshooting."""
        diagnostics = self._storage.get_cached_diagnostics()
        return {
            "db_path": diagnostics.get("db_path"),
            "db_exists": diagnostics.get("db_exists"),
            "last_error": diagnostics.get("last_error"),
            "schema_version": diagnostics.get("schema_version"),
            "generated_at": diagnostics.get("generated_at"),
            "table_counts": diagnostics.get("table_counts", {}),
        }

    async def async_update(self) -> None:
        """Refresh diagnostics from storage."""
        await self._storage.async_run_diagnostics()
