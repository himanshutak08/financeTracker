"""Frontend registration for the Finance Tracker panel."""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web

from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_ENTRYPOINT,
    PANEL_FRONTEND_URL_PATH,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_WEB_COMPONENT_NAME,
    PANEL_STATIC_LOADED_KEY,
)


class FinanceTrackerPanelAssetView(HomeAssistantView):
    """Serve the Finance Tracker panel bundle from the current integration files."""

    requires_auth = False

    def __init__(self, url: str, asset_path: Path, version: str) -> None:
        """Initialize the panel asset view."""
        self.url = url
        self.name = f"api:finance_tracker:panel:{version}"
        self._asset_path = asset_path

    async def get(self, request: web.Request) -> web.Response:
        """Return the current panel JavaScript bundle."""
        if not self._asset_path.is_file():
            return web.Response(status=404, text="Not Found")

        return web.Response(
            body=self._asset_path.read_bytes(),
            content_type="text/javascript",
            headers={
                "Cache-Control": "no-store, max-age=0",
            },
        )


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register static panel assets and the Finance sidebar panel."""
    integration_dir = Path(__file__).resolve().parent
    panel_dir = integration_dir / "panel"
    manifest = json.loads((integration_dir / "manifest.json").read_text(encoding="utf-8"))
    integration_version = manifest["version"]
    panel_asset_url = (
        f"/api/finance_tracker/panel/"
        f"{integration_version.replace('.', '_')}/{PANEL_ENTRYPOINT}"
    )
    domain_data = hass.data.setdefault(DOMAIN, {})
    loaded_asset_urls = domain_data.setdefault(PANEL_STATIC_LOADED_KEY, set())
    if not isinstance(loaded_asset_urls, set):
        loaded_asset_urls = set()
        domain_data[PANEL_STATIC_LOADED_KEY] = loaded_asset_urls
    if panel_asset_url not in loaded_asset_urls:
        hass.http.register_view(
            FinanceTrackerPanelAssetView(
                panel_asset_url,
                panel_dir / PANEL_ENTRYPOINT,
                integration_version,
            )
        )
        loaded_asset_urls.add(panel_asset_url)

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
                "js_url": f"{panel_asset_url}?v={integration_version}",
            }
        },
        require_admin=True,
    )


def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Remove the Finance sidebar panel while retaining its static path."""
    async_remove_panel(hass, PANEL_FRONTEND_URL_PATH, warn_if_unknown=False)
