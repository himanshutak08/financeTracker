# Finance Tracker Working Spec

## Goal

Build and maintain an in-house finance tracker inside Home Assistant for recurring monthly obligations, actual payments, reminders, dashboard visibility, and month-over-month history.

This repository copy is the sanitized source-of-truth version for development. Do not commit live SQLite data, exported backups, secrets, or personal finance records.

## Product Requirements

- One recurring template can generate entries for every month.
- The system must keep the expense list itself, including each expense name, category, default amount, and due date or due day.
- The expense catalog should preserve month-by-month amount history.
- Each month must keep its own snapshot so later changes do not corrupt older history.
- Each entry must support:
  - stable template id
  - month key
  - due date or due day
  - scheduled amount
  - actual paid amount
  - remaining amount
  - status
  - paid date
  - notes
  - category and icon for grouping
- Status must support at least `pending`, `paid`, `partial`, and `overdue`.
- Amounts must be editable when a bill changes for a specific month.
- The system must support both fixed recurring amounts and per-month overrides.
- Reminders should exist for due items and upcoming items.
- The UI should expose current month, upcoming attention items, category totals, payment history, and future month projections.

## Approved Architecture

Use this stack unless explicitly changed:

- Home Assistant custom integration as the backend
- Dedicated Home Assistant custom panel as the primary UI
- SQLite for initial durable storage
- Home Assistant service actions for writes
- Home Assistant notifications for reminders
- Lovelace only for summaries and shortcuts

Do not revive:

- AppDaemon as the core finance runtime
- helper-chain CRUD workflows
- giant sensor-attribute payloads as the main app model
- markdown-ledger dashboards as the primary UX

## Product Priorities

1. Expense master management
2. Year setup workflow
3. Current month ledger
4. History and reporting
5. Reminder engine
6. Lovelace summaries

## Screen Structure

### Current Month

- Default landing screen
- Current month ledger only
- Sorted by due date
- Filters by status, category, and date
- Direct actions such as mark paid, partial payment, edit, and notes

### Add Expense

- Dedicated form to create and edit expense definitions
- Support monthly, one-time, annual, twice-yearly, and custom-month recurrence patterns
- Support amount, due rule, start month, end month, custom months, notes, and reminder settings

### Year Setup

- Copy prior year into a draft next-year plan
- Review recurring items
- Add or remove yearly items
- Adjust custom month rules and annual amounts
- Activate the year after review

### History

- Monthwise summaries
- Category breakdowns
- Paid vs planned trends
- Drill-down for past month details

### Settings

- Reminder rules
- Notification channels
- Currency and defaults
- Import and export behavior

## Data Model Direction

Use a relational model with separate concepts for master definitions, yearly planning, monthly execution, and payment history.

Core tables:

- `expense_templates`
- `template_month_rules`
- `year_plans`
- `year_plan_items`
- `month_entries`
- `payments`
- `notifications_log`
- `audit_events`

## Current Repository Checkpoint

- The source repo lives at `/homeassistant/finance-tracker`.
- The live Home Assistant integration path `/homeassistant/custom_components/finance_tracker` is a symlink to the repo version for direct runtime testing.
- SQLite initialization and schema bootstrap are implemented in the integration.
- Write services cover expense management, year generation, payment recording, partial payments, month-entry updates, and payment undo.
- Read models exist for expense listing, current month ledger, and year plan retrieval.
- A websocket API exposes those read models to the panel frontend.
- The panel implements Current Month, expense management, Year Setup, History, and Settings workflows.
- A scheduled reminder engine delivers deduplicated upcoming, due, and overdue notifications through Home Assistant services.

## Recommended Implementation Path

1. Add backend tests for storage, recurrence generation, payments, payment undo, and year copying.
2. Fix integration metadata and complete the Home Assistant config-entry lifecycle.
3. Build expense management in the panel: list, add, edit, and archive.
4. Build year setup: generate or copy, review, adjust, and activate a plan.
5. Complete Current Month with filters, partial payments, entry editing, and notes.
6. Add history APIs and UI for monthly and category reporting.
7. Implement reminder scheduling, notification delivery, deduplication, and settings.
8. Make the repository ready for HACS import and distribution:
   - replace placeholder manifest URLs and code owners
   - validate `hacs.json` and the custom integration repository structure
   - add installation, configuration, upgrade, and removal instructions
   - add release tags and GitHub release notes
   - test a clean HACS custom-repository install in Home Assistant
   - test upgrades while preserving the SQLite database and applying schema migrations

HACS is the intended distribution and update mechanism. Home Assistant remains the runtime, and direct local installation remains the development workflow.

## Development Rules

- Keep this repo as the full source of truth for code and sanitized project context.
- Do not commit live Home Assistant runtime state from `/homeassistant`.
- Do not commit SQLite databases, backups, secrets, or personal finance data.
- Use HACS later for release and distribution validation, not for day-to-day inner-loop development.
