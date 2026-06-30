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

        self.assertEqual(manifest["version"], "0.2.9")

    def test_registered_panel_name_matches_custom_element(self) -> None:
        constants = (INTEGRATION / "const.py").read_text()
        frontend_source = (INTEGRATION / "frontend.py").read_text()
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn('PANEL_WEB_COMPONENT_NAME = "finance-tracker-panel"', constants)
        self.assertIn("panel_element_name = f\"{PANEL_WEB_COMPONENT_NAME}-{integration_version.replace('.', '-')}\"", frontend_source)
        self.assertIn("FINANCE_TRACKER_PANEL_ELEMENT", panel_source)
        self.assertIn("customElements.define(FINANCE_TRACKER_PANEL_ELEMENT, FinanceTrackerPanel)", panel_source)

    def test_panel_uses_host_theme_and_preserves_form_state(self) -> None:
        frontend_source = (INTEGRATION / "frontend.py").read_text()
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn('"embed_iframe": False', frontend_source)
        self.assertIn("async_remove_panel(hass, PANEL_FRONTEND_URL_PATH", frontend_source)
        self.assertIn("?v={integration_version}", frontend_source)
        self.assertIn("class FinanceTrackerPanelAssetView", frontend_source)
        self.assertIn("hass.http.register_view", frontend_source)
        self.assertIn("Cache-Control", frontend_source)
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

    def test_import_uses_panel_websocket_command(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()
        websocket_source = (INTEGRATION / "websocket_api.py").read_text()

        self.assertIn('type: "finance_tracker/import_expenses_file"', panel_source)
        self.assertNotIn('"import_expenses_file",\n        { filename', panel_source)
        self.assertIn('"finance_tracker/import_expenses_file"', websocket_source)
        self.assertIn("parse_expense_file", websocket_source)

    def test_bulk_import_explains_year_generation_next_step(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn("Import creates reusable expense definitions only", panel_source)
        self.assertIn("Click Generate ${this._escape(this._planYear)}", panel_source)
        self.assertIn("Next: Generate ${this._escape(this._planYear)}", panel_source)
        self.assertIn("After importing expenses, generate this year", panel_source)

    def test_panel_has_no_stale_scaffold_copy(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertNotIn("only Current Month is implemented", panel_source)
        self.assertNotIn("first panel milestone", panel_source)

    def test_panel_includes_mobile_header_and_responsive_guards(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn('<div class="app-header">Finance</div>', panel_source)
        self.assertIn(".app-header { display: flex; }", panel_source)
        self.assertIn("overflow-x: hidden", panel_source)
        self.assertIn("overflow-x: auto", panel_source)
        self.assertIn("grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr)", panel_source)
        self.assertIn("@media (max-width: 420px)", panel_source)


if __name__ == "__main__":
    unittest.main()
