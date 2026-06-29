# Finance Tracker

Finance Tracker is a Home Assistant custom integration plus dedicated panel UI for managing recurring expenses, yearly planning, monthly ledger execution, payment history, and reminder workflows.

## Development model

This repository is the source of truth for the project.

- Use direct local development during implementation.
- Keep the live integration under `/homeassistant/custom_components/finance_tracker`.
- Use HACS later for distribution testing and releases, not for every code change.

Project context and workflow docs live in:

- `docs/working-spec.md`
- `docs/development-workflow.md`
- `docs/legacy-archive.md`

## Initial scope

The first implementation phases are:

1. SQLite schema, migrations, and backend tests
2. Core write services
3. Current Month backend read models
4. Dedicated panel routes and complete user workflows
5. Reminder engine
6. HACS import, clean-install validation, and release packaging

## Current implementation checkpoint

- SQLite storage and schema bootstrap are implemented in the custom integration.
- Write services now cover expense management, year generation, payment recording, partial payments, month-entry updates, and payment undo.
- Read models exist for expense listing, current month ledger, and year plan retrieval.
- A websocket API now exposes those read models to the panel.
- Home Assistant UI setup is supported through a single-instance config flow.
- The sidebar panel provides Current Month, expense management, bulk import, Year Setup, History, and Settings workflows.
- Bulk Import accepts UTF-8 CSV and Excel XLSX files with up to 1,000 expense definitions and provides a downloadable sample CSV.
- Current Month supports month, status, and category filters; full or partial payments; and month-specific amount, due-date, category, and note editing.
- History provides annual totals, monthly paid-vs-planned drill-downs, category breakdowns, and recorded payment transactions.
- The reminder engine periodically delivers deduplicated upcoming, due, and overdue notifications through a configurable Home Assistant notification service.
- Settings controls currency, reminder enablement, notification service, scan interval, and manual reminder scans.

## Backend tests

Run the self-contained SQLite storage regression tests with:

```bash
python3 -m unittest discover -s tests -v
```

The tests use temporary databases and do not read or modify live Home Assistant data.

## Install with HACS

Until the repository is added to the default HACS catalog, install it as a custom repository:

1. In HACS, open **Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Add `https://github.com/himanshutak08/financeTracker` with category **Integration**.
4. Find **Finance Tracker** in HACS and install it.
5. Restart Home Assistant.
6. Open **Settings → Devices & services → Add integration**, search for **Finance Tracker**, and confirm setup.
7. Open **Finance** from the Home Assistant sidebar.

The panel is admin-only. Finance data is stored locally in `config/finance/tracker.db` and is not committed to this repository.

## Upgrade

1. Back up Home Assistant, including `config/finance/tracker.db`.
2. Install the Finance Tracker update from HACS.
3. Restart Home Assistant.
4. Open the Finance panel and verify the diagnostic sensor reports `ready`.

Database migrations run automatically during startup and preserve existing records. Never replace the database with files from a release archive.

## Remove

1. Remove Finance Tracker from **Settings → Devices & services**.
2. Remove the integration through HACS and restart Home Assistant.
3. Removing the integration stops reminder scheduling, unregisters services, unloads entities, and removes the Finance sidebar panel.
4. The SQLite database is intentionally retained. Delete `config/finance/tracker.db` manually only if all finance history should be permanently removed.

## Releases

HACS releases should use semantic version tags such as `v0.2.0`. The tag version must match `custom_components/finance_tracker/manifest.json`, and each GitHub release should summarize migrations and user-visible changes.

## Planned repository structure

```text
custom_components/finance_tracker/
  panel/
scripts/
docs/
```
