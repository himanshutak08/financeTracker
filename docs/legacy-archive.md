# Legacy Archive Notes

## Purpose

`/homeassistant/finance/legacy_cleanup_20260626/` is an external archive of the pre-reset finance implementation.

It exists for reference only and is not part of the active product path.

## Why It Stays Outside Git

The archive contains disabled Home Assistant config fragments, old Python modules, backups, and SQLite artifacts from the abandoned implementation path.

That material should not be reintroduced into the active repo because the approved architecture has changed.

## What The Active Repo Keeps Instead

The active repository keeps:

- current integration source
- current panel source
- sanitized product and architecture docs
- build and packaging files needed for distribution

## What The Archive Represents

The archived material is useful only for historical reference during migration discussions, such as:

- what was removed during the reset
- how earlier dashboard-heavy flows were structured
- where old helper or AppDaemon logic used to live

## Current Rule

Do not copy legacy runtime files, dashboards, backups, or databases into this repository.

If a legacy idea is worth reviving, reimplement it against the approved architecture instead of restoring the old files directly.
