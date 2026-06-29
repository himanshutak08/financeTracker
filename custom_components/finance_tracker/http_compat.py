"""HTTP compatibility helpers for static path registration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

try:
    from homeassistant.components.http import StaticPathConfig

    async def async_register_static_path(
        hass: HomeAssistant,
        url_path: str,
        path: str,
        cache_headers: bool = True,
    ) -> None:
        """Register a static path with current Home Assistant APIs."""
        await hass.http.async_register_static_paths(
            [StaticPathConfig(url_path, path, cache_headers)]
        )

except ImportError:

    async def async_register_static_path(
        hass: HomeAssistant,
        url_path: str,
        path: str,
        cache_headers: bool = True,
    ) -> None:
        """Register a static path with legacy Home Assistant APIs."""
        hass.http.register_static_path(url_path, path, cache_headers)
