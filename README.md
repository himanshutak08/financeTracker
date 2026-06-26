# Finance Tracker

Finance Tracker is a Home Assistant custom integration plus dedicated panel UI for managing recurring expenses, yearly planning, monthly ledger execution, payment history, and reminder workflows.

## Development model

This repository is the source of truth for the project.

- Use direct local development during implementation.
- Keep the live integration under `/homeassistant/custom_components/finance_tracker`.
- Use HACS later for distribution testing and releases, not for every code change.

## Initial scope

The first implementation phases are:

1. SQLite schema and migrations
2. Core write services
3. Current Month backend read models
4. Dedicated panel routes
5. Reminder engine

## Planned repository structure

```text
custom_components/finance_tracker/
panel/
scripts/
```
