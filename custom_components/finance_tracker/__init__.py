"""Finance Tracker integration bootstrap."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS, SERVICES_KEY, STORAGE_KEY
from .services import FinanceTrackerServiceManager
from .storage import FinanceTrackerStorage

type FinanceTrackerConfigEntry = ConfigEntry


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    if STORAGE_KEY not in domain_data:
        storage = FinanceTrackerStorage(hass)
        await storage.async_initialize()
        domain_data[STORAGE_KEY] = storage

    if SERVICES_KEY not in domain_data:
        services = FinanceTrackerServiceManager(hass, domain_data[STORAGE_KEY])
        await services.async_setup()
        domain_data[SERVICES_KEY] = services

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: FinanceTrackerConfigEntry
) -> bool:
    """Set up Finance Tracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: FinanceTrackerConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
