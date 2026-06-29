# Finance Panel

This directory contains the dedicated Finance Tracker panel frontend.

## Routes

- `/finance/current`
- `/finance/add`
- `/finance/year-setup`
- `/finance/history`
- `/finance/settings`

## Current milestone

The first panel milestone is now in place:

- `entrypoint.js` registers the panel custom element.
- The Current Month route loads ledger data through websocket commands.
- The Current Month route can trigger the backend `mark_paid` service for quick-pay flows.
- The remaining routes are scaffold placeholders for the next implementation slices.
