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

1. SQLite schema and migrations
2. Core write services
3. Current Month backend read models
4. Dedicated panel routes
5. Reminder engine

## Current implementation checkpoint

- SQLite storage and schema bootstrap are implemented in the custom integration.
- Write services now cover expense management, year generation, payment recording, partial payments, month-entry updates, and payment undo.
- Read models exist for expense listing, current month ledger, and year plan retrieval.
- A websocket API now exposes those read models to the panel.
- A first sidebar panel shell now exists at `/finance/current` with scaffolded routes for Add Expense, Year Setup, History, and Settings.
- The Current Month route can load the live ledger and trigger a quick `mark_paid` action.

## Planned repository structure

```text
custom_components/finance_tracker/
panel/
scripts/
docs/
```
