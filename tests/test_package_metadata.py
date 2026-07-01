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

    def test_forum_screenshot_asset_plan_is_packaged(self) -> None:
        asset_plan = ROOT / "forum-assets" / "screenshots.json"
        data = json.loads(asset_plan.read_text())

        self.assertTrue(asset_plan.is_file())
        self.assertGreaterEqual(len(data["screenshots"]), 6)
        self.assertEqual(data["gifs"][0]["id"], "first-use-flow")

    def test_mobile_qa_checklist_is_packaged(self) -> None:
        qa_plan = ROOT / "forum-assets" / "mobile-qa.json"
        data = json.loads(qa_plan.read_text())
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertTrue(qa_plan.is_file())
        self.assertIn("Hamburger menu opens", json.dumps(data))
        self.assertIn("min-height: 44px", panel_source)

    def test_github_issue_templates_are_packaged(self) -> None:
        issue_dir = ROOT / ".github" / "ISSUE_TEMPLATE"

        self.assertTrue((issue_dir / "bug_report.yml").is_file())
        self.assertTrue((issue_dir / "feature_request.yml").is_file())
        self.assertTrue((issue_dir / "import_csv_issue.yml").is_file())
        self.assertIn("finance_tracker", (issue_dir / "bug_report.yml").read_text())

    def test_readme_has_community_ready_sections(self) -> None:
        readme = (ROOT / "README.md").read_text()

        self.assertIn("HACS-Custom", readme)
        self.assertIn("## Compatibility", readme)
        self.assertIn("## Export and backup", readme)
        self.assertIn("## Known limitations", readme)
        self.assertIn("## Roadmap", readme)
        self.assertIn("## Support and feedback", readme)
        self.assertIn("Payment undo", readme)
        self.assertIn("Wipe a selected month ledger", readme)

    def test_community_forum_post_draft_is_packaged(self) -> None:
        draft_path = ROOT / "forum-assets" / "community-post.json"
        draft = json.loads(draft_path.read_text())

        self.assertIn("Finance Tracker", draft["title"])
        self.assertIn("Share your Projects", draft["category"])
        self.assertIn("https://github.com/himanshutak08/financeTracker", draft["body"])

    def test_release_version_matches_panel_cache_hotfix(self) -> None:
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())

        self.assertEqual(manifest["version"], "0.3.10")

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

    def test_current_month_empty_state_has_getting_started_checklist(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn("Getting started", panel_source)
        self.assertIn("Current Month appears after you add expenses", panel_source)
        self.assertIn('data-route="import">Bulk Import', panel_source)
        self.assertIn('data-route="year-setup">Year Setup', panel_source)

    def test_panel_exposes_csv_exports_for_expenses_current_and_history(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn("exportExpensesCsv()", panel_source)
        self.assertIn("exportCurrentMonthCsv()", panel_source)
        self.assertIn("exportHistoryCsv()", panel_source)
        self.assertIn("downloadCsv(filename, columns, rows)", panel_source)
        self.assertIn("data-export-expenses", panel_source)
        self.assertIn("data-export-current", panel_source)
        self.assertIn("data-export-history", panel_source)
        self.assertIn('class="history-actions"', panel_source)
        self.assertIn('class="history-filter"', panel_source)
        self.assertIn('for="history-year"', panel_source)

    def test_settings_exposes_safe_cleanup_tools(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()
        websocket_source = (INTEGRATION / "websocket_api.py").read_text()
        storage_source = (INTEGRATION / "storage.py").read_text()

        self.assertIn("data-delete-year-form", panel_source)
        self.assertIn("data-delete-month-form", panel_source)
        self.assertIn("data-generate-month-form", panel_source)
        self.assertIn("data-generate-current-month", panel_source)
        self.assertIn("data-reset-database", panel_source)
        self.assertIn("data-clear-reminder-log", panel_source)
        self.assertIn('type: "finance_tracker/delete_year_plan"', panel_source)
        self.assertIn('type: "finance_tracker/delete_month"', panel_source)
        self.assertIn('type: "finance_tracker/generate_month"', panel_source)
        self.assertIn('type: "finance_tracker/reset_database"', panel_source)
        self.assertIn('type: "finance_tracker/clear_reminder_log"', panel_source)
        self.assertIn('"finance_tracker/delete_year_plan"', websocket_source)
        self.assertIn('"finance_tracker/delete_month"', websocket_source)
        self.assertIn('"finance_tracker/generate_month"', websocket_source)
        self.assertIn('"finance_tracker/reset_database"', websocket_source)
        self.assertIn('"finance_tracker/clear_reminder_log"', websocket_source)
        self.assertIn("async_delete_year_plan", storage_source)
        self.assertIn("async_delete_month", storage_source)
        self.assertIn("async_generate_month", storage_source)
        self.assertIn("async_reset_database", storage_source)
        self.assertIn("async_clear_reminder_log", storage_source)

    def test_panel_uses_settings_currency_for_display_amounts(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn("this.loadSettings(true)", panel_source)
        self.assertIn("formatAmount(value)", panel_source)
        self.assertIn("new Intl.NumberFormat", panel_source)
        self.assertIn("this._settings?.currency", panel_source)
        self.assertIn("this.formatAmount(summary.scheduled_total", panel_source)
        self.assertIn("this.formatAmount(payment.amount)", panel_source)

    def test_high_impact_actions_require_confirmation(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn("Mark ${entry.name} as paid", panel_source)
        self.assertIn("Safe delete ${expense.name}", panel_source)
        self.assertIn("Reactivate ${expense.name}", panel_source)
        self.assertIn("Generate or rebuild the ${this._planYear} draft", panel_source)
        self.assertIn("Activate the ${this._planYear} plan", panel_source)
        self.assertIn("Copy ${sourceYear} into ${targetYear}", panel_source)
        self.assertIn("Delete the ${planYear} Finance Tracker year plan", panel_source)
        self.assertIn("Wipe the ${targetMonth} month ledger", panel_source)
        self.assertIn("Type RESET to continue", panel_source)

    def test_panel_exposes_payment_undo_actions(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()
        storage_source = (INTEGRATION / "storage.py").read_text()

        self.assertIn("undoPayment(paymentId", panel_source)
        self.assertIn("data-undo-payment", panel_source)
        self.assertIn('"undo_payment"', panel_source)
        self.assertIn("latest_payment_id", storage_source)
        self.assertIn("latest_payment_amount", storage_source)

    def test_expense_catalog_exposes_safe_delete_and_reactivate(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()
        storage_source = (INTEGRATION / "storage.py").read_text()

        self.assertIn("Safe delete", panel_source)
        self.assertIn("data-expense-reactivate", panel_source)
        self.assertIn("reactivateExpense(templateId)", panel_source)
        self.assertIn("Archived expense", storage_source)
        self.assertIn("Reactivate it instead", storage_source)

    def test_expense_catalog_exposes_bulk_actions_and_edit_focus(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()
        services_source = (INTEGRATION / "services.py").read_text()
        storage_source = (INTEGRATION / "storage.py").read_text()

        self.assertIn("data-expense-select-all", panel_source)
        self.assertIn("data-expense-bulk-archive", panel_source)
        self.assertIn("data-expense-bulk-delete", panel_source)
        self.assertIn("scrollIntoView", panel_source)
        self.assertIn("data-expense-editor", panel_source)
        self.assertIn("SERVICE_DELETE_EXPENSES", services_source)
        self.assertIn("async_delete_expenses", storage_source)
        self.assertIn("has generated history", storage_source)

    def test_settings_exposes_companion_app_notifications(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()
        reminder_source = (INTEGRATION / "reminders.py").read_text()
        storage_source = (INTEGRATION / "storage.py").read_text()

        self.assertIn("mobile_notification_service", panel_source)
        self.assertIn("mobile_app_", panel_source)
        self.assertIn("data-test-mobile-notification", panel_source)
        self.assertIn("mobile_notification_service", reminder_source)
        self.assertIn('"mobile_notification_service": ""', storage_source)

    def test_settings_has_currency_chooser_and_accessible_statuses(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn("₹ Indian Rupee (INR)", panel_source)
        self.assertIn("€ Euro (EUR)", panel_source)
        self.assertIn('<input id="settings-currency"', panel_source)
        self.assertIn('list="settings-currencies"', panel_source)
        self.assertIn('pattern="[A-Za-z]{3}"', panel_source)
        self.assertIn("enter a three-letter code", panel_source)
        self.assertIn("align-content: start", panel_source)
        self.assertIn('settings.currency || "INR"', panel_source)
        self.assertIn('aria-label="Finance sections"', panel_source)
        self.assertIn('aria-current="page"', panel_source)
        self.assertIn('role="alert"', panel_source)
        self.assertIn('aria-live="polite"', panel_source)

    def test_empty_states_offer_next_actions(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn("No expenses yet.", panel_source)
        self.assertIn("No plan is loaded for ${this._planYear}.", panel_source)
        self.assertIn("No ledger history exists", panel_source)
        self.assertIn("No payments recorded for this year.", panel_source)
        self.assertIn('data-route="year-setup">Open Year Setup', panel_source)
        self.assertIn('data-route="current">Open Current Month', panel_source)
        self.assertIn("Generate this month", panel_source)
        self.assertIn("If this month was wiped", panel_source)
        self.assertIn('querySelectorAll("[data-year-generate]")', panel_source)

    def test_panel_buttons_keep_intended_visual_style(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertNotIn(".toolbar button,\n        .pay-button", panel_source)
        self.assertIn('class="secondary-button" data-refresh', panel_source)
        self.assertIn('class="secondary-button" data-expense-refresh', panel_source)
        self.assertIn('class="primary-button" data-year-activate', panel_source)
        self.assertIn("toolbar .form-actions", panel_source)
        self.assertIn(".entry-tools summary::-webkit-details-marker", panel_source)

    def test_panel_has_no_stale_scaffold_copy(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertNotIn("only Current Month is implemented", panel_source)
        self.assertNotIn("first panel milestone", panel_source)

    def test_panel_includes_mobile_header_and_responsive_guards(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn('<div class="app-header">', panel_source)
        self.assertIn('data-toggle-menu aria-label="Open Home Assistant menu"', panel_source)
        self.assertIn('new Event("hass-toggle-menu", { bubbles: true, composed: true })', panel_source)
        self.assertIn(".app-header { display: flex; }", panel_source)
        self.assertIn("overflow-x: hidden", panel_source)
        self.assertIn("overflow-x: auto", panel_source)
        self.assertIn("grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr)", panel_source)
        self.assertIn("@media (max-width: 420px)", panel_source)

    def test_visual_polish_and_collapsible_year_plan_are_present(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn("Track household expenses, dues, and payments in one place.", panel_source)
        self.assertIn("button:focus-visible", panel_source)
        self.assertIn(".expense-card.selected", panel_source)
        self.assertIn(".month-group[open]", panel_source)
        self.assertIn('<details class="month-group"', panel_source)
        self.assertIn('<summary class="month-heading">', panel_source)
        self.assertIn('<summary class="partial-action" role="button">', panel_source)
        self.assertIn('<summary class="edit-action" role="button">', panel_source)
        self.assertNotIn("Plan, pay, and stay ahead.", panel_source)

    def test_status_and_archive_styles_use_high_contrast_tokens(self) -> None:
        panel_source = (INTEGRATION / "panel" / "entrypoint.js").read_text()

        self.assertIn("color: var(--success-color, #166534)", panel_source)
        self.assertIn("color: var(--error-color, #b91c1c)", panel_source)
        self.assertIn(".badge.archived", panel_source)
        self.assertIn('<span class="badge archived">Archived</span>', panel_source)
        self.assertNotIn("color: #86efac", panel_source)
        self.assertNotIn("color: #fca5a5", panel_source)


if __name__ == "__main__":
    unittest.main()
