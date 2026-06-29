"""Tests for Home Assistant and HACS package metadata."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "finance_tracker"


class PackageMetadataTests(unittest.TestCase):
    def test_manifest_declares_config_flow_and_real_project_links(self) -> None:
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())

        self.assertEqual(manifest["domain"], "finance_tracker")
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["codeowners"], ["@himanshutak08"])
        self.assertNotIn("REPLACE_ME", json.dumps(manifest))
        self.assertTrue((INTEGRATION / "config_flow.py").is_file())
        self.assertTrue((INTEGRATION / "panel" / "entrypoint.js").is_file())

    def test_hacs_metadata_targets_the_integration_domain(self) -> None:
        hacs = json.loads((ROOT / "hacs.json").read_text())

        self.assertFalse(hacs["content_in_root"])
        self.assertNotIn("domains", hacs)

    def test_hacs_brand_assets_are_packaged(self) -> None:
        brand = INTEGRATION / "brand"

        self.assertTrue((brand / "icon.png").is_file())
        self.assertTrue((brand / "icon@2x.png").is_file())

    def test_release_version_matches_panel_cache_hotfix(self) -> None:
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())

        self.assertEqual(manifest["version"], "0.2.4")

    def test_registered_panel_name_matches_custom_element(self) -> None:
        constants = (INTEGRATION / "const.py").read_text()
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn('PANEL_WEB_COMPONENT_NAME = "finance-tracker-panel"', constants)
        self.assertIn(
            'customElements.define("finance-tracker-panel", FinanceTrackerPanel)',
            panel_source,
        )

    def test_panel_uses_host_theme_and_preserves_form_state(self) -> None:
        frontend_source = (INTEGRATION / "frontend.py").read_text()
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn('"embed_iframe": False', frontend_source)
        self.assertIn("async_remove_panel(hass, PANEL_FRONTEND_URL_PATH", frontend_source)
        self.assertIn("?v={integration_version}", frontend_source)
        self.assertIn("static_url = f\"{PANEL_STATIC_URL}_{integration_version.replace('.', '_')}\"", frontend_source)
        hass_setter = panel_source.split("set hass(hass)", 1)[1].split(
            "disconnectedCallback", 1
        )[0]
        self.assertNotIn("this.render();\n  }", hass_setter)

    def test_config_entry_removal_preserves_database(self) -> None:
        integration_source = (INTEGRATION / "__init__.py").read_text()

        self.assertIn("async def async_remove_entry", integration_source)
        self.assertIn("async_unregister_frontend(hass)", integration_source)
        self.assertIn("await async_register_frontend(hass)", integration_source)
        self.assertNotIn("if not domain_data.get(FRONTEND_LOADED_KEY)", integration_source)
        self.assertNotIn("unlink(", integration_source)


if __name__ == "__main__":
    unittest.main()
