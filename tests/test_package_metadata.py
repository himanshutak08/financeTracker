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
        self.assertIn("finance_tracker", hacs["domains"])

    def test_release_version_matches_expected_first_hacs_release(self) -> None:
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())

        self.assertEqual(manifest["version"], "0.1.0")


if __name__ == "__main__":
    unittest.main()
