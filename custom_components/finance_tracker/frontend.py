"""Frontend registration for the Finance Tracker panel."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_ENTRYPOINT,
    PANEL_FRONTEND_URL_PATH,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_WEB_COMPONENT_NAME,
    PANEL_STATIC_LOADED_KEY,
)
from .http_compat import async_register_static_path


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register static panel assets and the Finance sidebar panel."""
    integration_dir = Path(__file__).resolve().parent
    panel_dir = integration_dir / "panel"
    manifest = json.loads((integration_dir / "manifest.json").read_text(encoding="utf-8"))
    integration_version = manifest["version"]
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get(PANEL_STATIC_LOADED_KEY):
        await async_register_static_path(
            hass,
            PANEL_STATIC_URL,
            str(panel_dir),
            cache_headers=False,
        )
        domain_data[PANEL_STATIC_LOADED_KEY] = True

    async_remove_panel(hass, PANEL_FRONTEND_URL_PATH, warn_if_unknown=False)

    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_FRONTEND_URL_PATH,
        config={
            "_panel_custom": {
                "name": PANEL_WEB_COMPONENT_NAME,
                "embed_iframe": False,
                "trust_external": False,
                "js_url": f"{PANEL_STATIC_URL}/{PANEL_ENTRYPOINT}?v={integration_version}",
            }
        },
        require_admin=True,
    )


def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Remove the Finance sidebar panel while retaining its static path."""
    async_remove_panel(hass, PANEL_FRONTEND_URL_PATH, warn_if_unknown=False)
