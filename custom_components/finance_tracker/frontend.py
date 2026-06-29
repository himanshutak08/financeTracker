"""Frontend registration for the Finance Tracker panel."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.core import HomeAssistant

from .const import (
    PANEL_ENTRYPOINT,
    PANEL_FRONTEND_URL_PATH,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_WEB_COMPONENT_NAME,
)
from .http_compat import async_register_static_path


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register static panel assets and the Finance sidebar panel."""
    panel_dir = Path(__file__).resolve().parent / "panel"
    await async_register_static_path(
        hass,
        PANEL_STATIC_URL,
        str(panel_dir),
        cache_headers=False,
    )

    if PANEL_FRONTEND_URL_PATH in hass.data.get("frontend_panels", {}):
        return

    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_FRONTEND_URL_PATH,
        config={
            "_panel_custom": {
                "name": PANEL_WEB_COMPONENT_NAME,
                "embed_iframe": True,
                "trust_external": False,
                "js_url": f"{PANEL_STATIC_URL}/{PANEL_ENTRYPOINT}",
            }
        },
        require_admin=True,
    )
