"""Finance Tracker integration bootstrap."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform

from .const import (
    DOMAIN,
    FRONTEND_LOADED_KEY,
    PLATFORMS,
    REMINDER_MANAGER_KEY,
    SERVICES_KEY,
    STORAGE_KEY,
    WEBSOCKET_API_LOADED_KEY,
    YAML_SENSOR_LOADED_KEY,
)
from .frontend import async_register_frontend
from .reminders import FinanceTrackerReminderManager
from .services import FinanceTrackerServiceManager
from .storage import FinanceTrackerStorage
from .websocket_api import async_register_websocket_commands

type FinanceTrackerConfigEntry = ConfigEntry

LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def _async_setup_runtime(hass: HomeAssistant) -> None:
    """Initialize shared storage, services, APIs, and frontend exactly once."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    if STORAGE_KEY not in domain_data:
        storage = FinanceTrackerStorage(hass)
        await storage.async_initialize()
        domain_data[STORAGE_KEY] = storage

    if SERVICES_KEY not in domain_data:
        services = FinanceTrackerServiceManager(hass, domain_data[STORAGE_KEY])
        await services.async_setup()
        domain_data[SERVICES_KEY] = services

    if REMINDER_MANAGER_KEY not in domain_data:
        reminder_manager = FinanceTrackerReminderManager(
            hass, domain_data[STORAGE_KEY]
        )
        await reminder_manager.async_setup()
        domain_data[REMINDER_MANAGER_KEY] = reminder_manager

    if not domain_data.get(WEBSOCKET_API_LOADED_KEY):
        try:
            async_register_websocket_commands(hass)
        except Exception:
            LOGGER.exception("Failed to register Finance Tracker websocket commands")
        else:
            domain_data[WEBSOCKET_API_LOADED_KEY] = True

    if not domain_data.get(FRONTEND_LOADED_KEY):
        try:
            await async_register_frontend(hass)
        except Exception:
            LOGGER.exception("Failed to register Finance Tracker frontend")
        else:
            domain_data[FRONTEND_LOADED_KEY] = True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration and retain YAML support for development."""
    await _async_setup_runtime(hass)

    domain_data = hass.data[DOMAIN]
    if DOMAIN in config and not domain_data.get(YAML_SENSOR_LOADED_KEY):
        await async_load_platform(hass, "sensor", DOMAIN, {}, config)
        domain_data[YAML_SENSOR_LOADED_KEY] = True

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: FinanceTrackerConfigEntry
) -> bool:
    """Set up Finance Tracker from a config entry."""
    await _async_setup_runtime(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: FinanceTrackerConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
