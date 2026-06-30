# Finance Tracker for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5.svg)](https://www.home-assistant.io/)
[![Local First](https://img.shields.io/badge/Data-Local%20First-success.svg)](#data-and-privacy)

Finance Tracker is a Home Assistant custom integration for managing household expenses inside Home Assistant. It adds a dedicated **Finance** sidebar panel where you can maintain recurring expenses, generate a yearly plan, track the current month, record payments, review history, and receive reminder notifications.

The integration is designed for local-first personal finance tracking. Your data is stored in your Home Assistant config directory and is not sent to an external finance service.

## Features

- Dedicated Home Assistant sidebar panel.
- Expense catalog for recurring and one-time expenses.
- Bulk CSV/XLSX import with a downloadable sample CSV.
- Year setup workflow to generate, review, and activate an annual expense plan.
- Current Month ledger with unpaid items shown first.
- Full and partial payment recording.
- Payment undo from Current Month and History.
- Month-specific edits for amount, due date, category, and notes.
- History view with monthly, category, and payment breakdowns.
- CSV exports for expenses, current month, and history.
- Safe cleanup tools for rebuilding a generated year or clearing reminder delivery history.
- Configurable reminder notifications through Home Assistant notify services.
- Local SQLite storage at `config/finance/tracker.db`.

## Compatibility

- Distribution: HACS custom repository
- Home Assistant minimum version: `2026.6.0`
- Storage: local SQLite database
- Panel access: Home Assistant admin users

## Screenshots

Screenshots are planned for the Home Assistant Community forum post. The capture checklist is stored in `forum-assets/screenshots.json`.

## Installation with HACS

Finance Tracker is currently installed as a custom HACS repository.

1. Open **HACS → Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Add this repository:

   ```text
   https://github.com/himanshutak08/financeTracker
   ```

4. Select category **Integration**.
5. Install **Finance Tracker**.
6. Restart Home Assistant.
7. Go to **Settings → Devices & services → Add integration**.
8. Search for **Finance Tracker** and complete setup.
9. Open **Finance** from the Home Assistant sidebar.

## First use

Finance Tracker uses a simple setup flow:

1. Open **Finance → Add Expense** and add expenses manually, or open **Bulk Import** and upload a CSV/XLSX file.
2. Open **Year Setup**.
3. Click **Generate `<year>`** to create a draft yearly plan from your active expenses.
4. Review the generated months, amounts, and due dates.
5. Click **Activate year**.
6. Open **Current Month** to record payments.

Bulk import only creates expense definitions. Current Month entries appear after you generate and activate a year plan.

## Bulk import CSV format

The Bulk Import screen includes a **Download sample CSV** button. CSV files should be UTF-8 encoded.

Required columns:

```text
name,category,amount,recurrence
```

Optional columns:

```text
due_day,start_month,end_month,custom_months,icon,notes,reminder_days
```

Supported recurrence values:

- `monthly`
- `one_time`
- `annual`
- `twice_yearly`
- `custom_months`

For `custom_months`, use comma-separated month numbers such as `1,4,7,10`.

Example:

```csv
name,category,amount,recurrence,due_day,start_month,end_month,custom_months,icon,notes,reminder_days
Electricity,Utilities,2500,monthly,15,1,12,,mdi:lightning-bolt,Monthly power bill,3
Insurance,Insurance,12000,annual,10,4,4,,mdi:shield-home,Annual home insurance,7
Quarterly maintenance,Home,3000,custom_months,5,,,"1,4,7,10",mdi:tools,Quarterly maintenance,5
```

## Updating

1. Back up Home Assistant, including `config/finance/tracker.db`.
2. Update Finance Tracker from HACS.
3. Restart Home Assistant.
4. Reload the Finance panel in your browser or mobile app.

Database migrations run automatically during startup. Do not replace `config/finance/tracker.db` with files from a release archive.

## Export and backup

Use the Finance panel export buttons to download CSV snapshots:

- **Add Expense → Export CSV** for expense definitions.
- **Current Month → Export CSV** for the visible monthly ledger.
- **History → Export CSV** for yearly ledger and payment rows.

These exports are meant for reporting and backup review. Keep backing up `config/finance/tracker.db` as the source of truth.

## Maintenance tools

The Settings screen includes safe cleanup tools:

- Delete a generated year plan and its ledger rows.
- Wipe a selected month ledger and its payments.
- Clear reminder delivery history so eligible reminders can be sent again.
- Reset all Finance Tracker data after typing a confirmation phrase.

These actions require confirmation and do not delete expense definitions or remove the database.

## Removing

1. Remove Finance Tracker from **Settings → Devices & services**.
2. Remove the integration through HACS.
3. Restart Home Assistant.

Removing the integration unloads services, entities, reminders, and the Finance sidebar panel. The SQLite database is intentionally retained. Delete `config/finance/tracker.db` manually only if you want to permanently remove all finance history.

## Troubleshooting

### The Finance page still shows an old UI after updating

Restart Home Assistant after every HACS update. If an old tab was already open, reload the browser tab or close and reopen the Home Assistant mobile app.

### Bulk import succeeded but Current Month is empty

Open **Year Setup**, click **Generate `<year>`**, review the draft, then click **Activate year**. Bulk import creates expense definitions; Year Setup creates the monthly ledger.

### HACS download fails

Confirm that HACS is installing the latest release and that the repository is added as an **Integration** custom repository.

### Diagnostic entity reports an issue

Check **Settings → System → Logs** and search for `finance_tracker`.

## Known limitations

- Finance Tracker is not a bank sync integration.
- It does not connect to financial institutions or payment providers.
- Export CSV files are snapshots, not a full database restore format.
- Public testing is still early; keep regular Home Assistant backups.

## Roadmap

- Better dashboards and visual summaries.
- Optional import/restore workflow for exported data.
- More recurrence patterns.
- Additional reminder options.
- More polished mobile screenshots and forum examples.

## Data and privacy

Finance data is stored locally in:

```text
config/finance/tracker.db
```

The integration does not require a cloud finance account and does not send expense data to an external service.

## Support and feedback

Before opening an issue:

1. Update to the latest HACS release.
2. Restart Home Assistant.
3. Check logs for `finance_tracker`.
4. If reporting import problems, remove sensitive data and include only minimal sample rows.

Use the GitHub issue templates for bug reports, feature requests, and CSV/XLSX import issues.

## Development and validation

Run the test suite with:

```bash
python3 -m unittest discover -s tests -v
```

The tests use temporary databases and do not read or modify live Home Assistant data.
