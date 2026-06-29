# Development Workflow

## Repo Role

`/homeassistant/finance-tracker` is the source of truth for this project.

Keep code, sanitized specs, and developer workflow docs here. Do not treat `/homeassistant` as the git repository for finance tracker work.

## Recommended Split

- Mac: active development, frontend builds, linting, packaging, and git operations
- Home Assistant machine: live runtime validation inside Home Assistant

This avoids doing the expensive inner loop on the HA Pi while still testing against a real HA instance.

## Testing Options

### Preferred

Run a separate Home Assistant development instance on the Mac and mount or copy the repo into its `custom_components` path.

Use this for:

- backend service validation
- websocket and panel iteration
- schema and migration testing against throwaway databases

### Practical

Push from the Mac, pull on the Home Assistant machine, then restart or reload Home Assistant to validate against the live environment.

Use this for:

- final integration verification
- checking service registration
- checking sidebar panel loading
- confirming reminder and notification behavior

## Live Home Assistant Linkage

The current Home Assistant setup already loads the integration directly from the repo through this symlink:

`/homeassistant/custom_components/finance_tracker -> /homeassistant/finance-tracker/custom_components/finance_tracker`

That means HACS is not required for every test cycle.

## Recommended Inner Loop

1. Edit in the repo on the Mac.
2. Run local lint, tests, and frontend build on the Mac.
3. Push commits to git.
4. Pull the repo on the Home Assistant machine.
5. Restart Home Assistant or reload what can be reloaded safely.
6. Validate services, entities, websocket behavior, and panel routes.

## When To Use HACS

Use HACS for:

- clean-install validation
- release packaging checks
- distribution testing

Do not use HACS as the normal day-to-day development loop.

## Release Validation

Before tagging a release:

1. Run `python3 -m unittest discover -s tests -v`.
2. Confirm the HACS and Hassfest GitHub checks pass.
3. Install the repository as a HACS custom integration in a clean Home Assistant instance.
4. Complete UI setup and confirm the Finance sidebar panel loads.
5. Create sample data, upgrade from the previous release, and confirm the database schema version advances without data loss.
6. Verify removal leaves `config/finance/tracker.db` intact.

## Commit Hygiene

Safe to commit:

- integration source
- panel source
- build and packaging files that are intentionally part of distribution
- sanitized documentation

Do not commit:

- `*.db`
- `*.db-shm`
- `*.db-wal`
- Home Assistant `.storage` content
- `secrets.yaml`
- logs
- personal finance records
- throwaway local build output unless intentionally versioned
