"""SQLite-backed storage for the Finance Tracker integration."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DB_RELATIVE_PATH

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS expense_templates (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    icon TEXT,
    notes TEXT,
    recurrence TEXT NOT NULL,
    default_amount REAL NOT NULL,
    due_day INTEGER,
    due_date TEXT,
    start_month TEXT,
    end_month TEXT,
    reminder_days INTEGER NOT NULL DEFAULT 3,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS template_month_rules (
    rule_id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    month_number INTEGER NOT NULL,
    amount_override REAL,
    day_override INTEGER,
    month_date_override TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(template_id) REFERENCES expense_templates(template_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS year_plans (
    year_plan_id TEXT PRIMARY KEY,
    plan_year INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL,
    source_year INTEGER,
    created_at TEXT NOT NULL,
    activated_at TEXT
);

CREATE TABLE IF NOT EXISTS year_plan_items (
    plan_item_id TEXT PRIMARY KEY,
    year_plan_id TEXT NOT NULL,
    template_id TEXT NOT NULL,
    month_number INTEGER NOT NULL,
    scheduled_amount REAL NOT NULL,
    due_day INTEGER,
    due_date TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(year_plan_id) REFERENCES year_plans(year_plan_id) ON DELETE CASCADE,
    FOREIGN KEY(template_id) REFERENCES expense_templates(template_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS month_entries (
    entry_id TEXT PRIMARY KEY,
    plan_item_id TEXT NOT NULL,
    template_id TEXT NOT NULL,
    month_key TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    icon TEXT,
    scheduled_amount REAL NOT NULL,
    actual_paid_amount REAL NOT NULL DEFAULT 0,
    remaining_amount REAL NOT NULL,
    due_date TEXT,
    status TEXT NOT NULL,
    notes TEXT,
    paid_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(plan_item_id) REFERENCES year_plan_items(plan_item_id) ON DELETE CASCADE,
    FOREIGN KEY(template_id) REFERENCES expense_templates(template_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    amount REAL NOT NULL,
    paid_date TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(entry_id) REFERENCES month_entries(entry_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notifications_log (
    notification_id TEXT PRIMARY KEY,
    entry_id TEXT,
    reminder_type TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    channel TEXT,
    payload_json TEXT,
    FOREIGN KEY(entry_id) REFERENCES month_entries(entry_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    setting_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

RECURRENCE_TYPES = {
    "monthly",
    "one_time",
    "annual",
    "twice_yearly",
    "custom_months",
}

DEFAULT_SETTINGS = {
    "currency": "INR",
    "reminders_enabled": True,
    "notification_service": "persistent_notification.create",
    "scan_interval_minutes": 60,
}

SCHEMA_VERSION = 1


@dataclass(slots=True)
class FinanceTrackerStorage:
    """Persist finance data in SQLite."""

    hass: HomeAssistant
    _db_path: Path = field(init=False)
    _last_diagnostics: dict[str, Any] = field(init=False, default_factory=dict)
    _last_error: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        """Compute database path after dataclass initialization."""
        self._db_path = Path(self.hass.config.path(DB_RELATIVE_PATH))

    async def async_initialize(self) -> None:
        """Create database schema if needed."""
        try:
            await self.hass.async_add_executor_job(self._initialize_db)
            await self.async_run_diagnostics()
        except Exception as err:
            self._last_error = str(err)
            raise

    async def async_add_expense(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Create an expense template and any custom month rules."""
        return await self.hass.async_add_executor_job(self._add_expense, dict(payload))

    async def async_archive_expense(self, template_id: str) -> dict[str, Any]:
        """Deactivate an expense template."""
        return await self.hass.async_add_executor_job(self._archive_expense, template_id)

    async def async_copy_year(
        self, source_year: int, target_year: int
    ) -> dict[str, Any]:
        """Copy an existing year plan into a draft target year."""
        return await self.hass.async_add_executor_job(
            self._copy_year, source_year, target_year
        )

    async def async_update_expense(
        self, template_id: str, changes: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Update an expense template."""
        return await self.hass.async_add_executor_job(
            self._update_expense, template_id, dict(changes)
        )

    async def async_generate_year(self, plan_year: int) -> dict[str, Any]:
        """Build a draft year plan and month entries."""
        return await self.hass.async_add_executor_job(self._generate_year, plan_year)

    async def async_activate_year(self, plan_year: int) -> dict[str, Any]:
        """Mark a year plan as active."""
        return await self.hass.async_add_executor_job(self._activate_year, plan_year)

    async def async_delete_year_plan(self, plan_year: int) -> dict[str, Any]:
        """Delete one generated year plan and its ledger rows."""
        return await self.hass.async_add_executor_job(self._delete_year_plan, plan_year)

    async def async_clear_reminder_log(self) -> dict[str, Any]:
        """Clear reminder dedupe history without touching expenses or payments."""
        return await self.hass.async_add_executor_job(self._clear_reminder_log)

    async def async_delete_month(self, month_key: str) -> dict[str, Any]:
        """Delete one generated month ledger and its payments."""
        return await self.hass.async_add_executor_job(self._delete_month, month_key)

    async def async_generate_month(self, month_key: str) -> dict[str, Any]:
        """Rebuild one month ledger from an existing year plan."""
        return await self.hass.async_add_executor_job(self._generate_month, month_key)

    async def async_reset_database(self) -> dict[str, Any]:
        """Delete all Finance Tracker user data while keeping the schema."""
        return await self.hass.async_add_executor_job(self._reset_database)

    async def async_list_expenses(
        self, active_only: bool = False, category: str | None = None
    ) -> dict[str, Any]:
        """Return expense master rows for the app."""
        return await self.hass.async_add_executor_job(
            self._list_expenses, active_only, category
        )

    async def async_get_current_month(
        self,
        month_key: str | None = None,
        status: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Return the month ledger with summary totals."""
        return await self.hass.async_add_executor_job(
            self._get_current_month, month_key, status, category
        )

    async def async_get_year_plan(
        self, plan_year: int, month: int | None = None
    ) -> dict[str, Any]:
        """Return year plan details for planning and review."""
        return await self.hass.async_add_executor_job(
            self._get_year_plan, plan_year, month
        )

    async def async_get_history(self, plan_year: int) -> dict[str, Any]:
        """Return yearly ledger reporting and payment history."""
        return await self.hass.async_add_executor_job(self._get_history, plan_year)

    async def async_get_settings(self) -> dict[str, Any]:
        """Return application and reminder settings."""
        return await self.hass.async_add_executor_job(self._get_settings)

    async def async_update_settings(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        """Persist application and reminder settings."""
        return await self.hass.async_add_executor_job(
            self._update_settings, dict(changes)
        )

    async def async_get_reminder_candidates(
        self, today: str | None = None
    ) -> list[dict[str, Any]]:
        """Return due reminder candidates that have not been sent today."""
        return await self.hass.async_add_executor_job(
            self._get_reminder_candidates, today
        )

    async def async_log_notification(
        self,
        entry_id: str,
        reminder_type: str,
        dedupe_key: str,
        channel: str,
        payload: Mapping[str, Any],
    ) -> None:
        """Record a successfully delivered reminder."""
        await self.hass.async_add_executor_job(
            self._log_notification,
            entry_id,
            reminder_type,
            dedupe_key,
            channel,
            dict(payload),
        )

    async def async_mark_paid(
        self, entry_id: str, amount: float, paid_date: str | None, note: str | None
    ) -> dict[str, Any]:
        """Record a payment against a month entry."""
        return await self.hass.async_add_executor_job(
            self._mark_paid, entry_id, amount, paid_date, note
        )

    async def async_mark_partial(
        self, entry_id: str, amount: float, paid_date: str | None, note: str | None
    ) -> dict[str, Any]:
        """Record a partial payment against a month entry."""
        return await self.hass.async_add_executor_job(
            self._mark_partial, entry_id, amount, paid_date, note
        )

    async def async_update_month_entry(
        self, entry_id: str, changes: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Update a generated month entry snapshot."""
        return await self.hass.async_add_executor_job(
            self._update_month_entry, entry_id, dict(changes)
        )

    async def async_undo_payment(self, payment_id: str) -> dict[str, Any]:
        """Delete a recorded payment and recalculate the month entry."""
        return await self.hass.async_add_executor_job(self._undo_payment, payment_id)

    async def async_run_diagnostics(self) -> dict[str, Any]:
        """Collect lightweight backend diagnostics for validation."""
        diagnostics = await self.hass.async_add_executor_job(self._collect_diagnostics)
        self._last_diagnostics = diagnostics
        self._last_error = diagnostics.get("last_error")
        return diagnostics

    def get_cached_diagnostics(self) -> dict[str, Any]:
        """Return the most recent diagnostic snapshot."""
        if self._last_diagnostics:
            return dict(self._last_diagnostics)
        return {
            "db_path": str(self._db_path),
            "db_exists": self._db_path.exists(),
            "setup_status": "unknown",
            "last_error": self._last_error,
            "table_counts": {},
            "schema_version": None,
            "generated_at": None,
        }

    def _initialize_db(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA_SQL)
            self._apply_migrations(conn)
            with conn:
                yield conn
        finally:
            conn.close()

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """Upgrade the database schema without replacing user data."""
        current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current_version > SCHEMA_VERSION:
            raise HomeAssistantError(
                f"Database schema {current_version} is newer than supported version {SCHEMA_VERSION}"
            )

        # Version 1 adopts the initial relational schema. SCHEMA_SQL uses
        # idempotent CREATE statements, so pre-version databases keep all data.
        if current_version < 1:
            conn.execute("PRAGMA user_version = 1")

    def _collect_diagnostics(self) -> dict[str, Any]:
        diagnostics: dict[str, Any] = {
            "db_path": str(self._db_path),
            "db_exists": self._db_path.exists(),
            "setup_status": "missing_db",
            "last_error": self._last_error,
            "table_counts": {},
            "generated_at": datetime.now(UTC).isoformat(),
            "schema_version": None,
        }

        try:
            with self._connect() as conn:
                table_counts = {}
                diagnostics["schema_version"] = int(
                    conn.execute("PRAGMA user_version").fetchone()[0]
                )
                for table in (
                    "expense_templates",
                    "year_plans",
                    "year_plan_items",
                    "month_entries",
                    "payments",
                    "notifications_log",
                    "audit_events",
                ):
                    table_counts[table] = conn.execute(
                        f"SELECT COUNT(*) AS count FROM {table}"
                    ).fetchone()["count"]
        except Exception as err:
            diagnostics["setup_status"] = "db_error"
            diagnostics["last_error"] = str(err)
            return diagnostics

        diagnostics["db_exists"] = self._db_path.exists()
        diagnostics["setup_status"] = "ready"
        diagnostics["last_error"] = None
        diagnostics["table_counts"] = table_counts
        return diagnostics

    def _add_expense(self, payload: dict[str, Any]) -> dict[str, Any]:
        recurrence = payload["recurrence"]
        if recurrence not in RECURRENCE_TYPES:
            raise HomeAssistantError(f"Unsupported recurrence type: {recurrence}")

        amount = float(payload["amount"])
        due_day = payload.get("due_day")
        if due_day is not None and not 1 <= int(due_day) <= 31:
            raise HomeAssistantError("due_day must be between 1 and 31")

        start_month = payload.get("start_month")
        end_month = payload.get("end_month")
        custom_months = self._parse_custom_months(payload.get("custom_months"))
        month_amount_overrides = self._normalize_month_mapping(
            payload.get("month_amount_overrides")
        )
        month_day_overrides = self._normalize_month_mapping(
            payload.get("month_day_overrides")
        )
        now = _utcnow()
        template_id = uuid4().hex

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO expense_templates (
                    template_id, name, category, icon, notes, recurrence,
                    default_amount, due_day, due_date, start_month, end_month,
                    reminder_days, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    template_id,
                    payload["name"],
                    payload["category"],
                    payload.get("icon"),
                    payload.get("notes"),
                    recurrence,
                    amount,
                    due_day,
                    payload.get("due_date"),
                    start_month,
                    end_month,
                    int(payload.get("reminder_days", 3)),
                    now,
                    now,
                ),
            )
            self._replace_month_rules(
                conn,
                template_id,
                custom_months,
                month_amount_overrides,
                month_day_overrides,
            )
            self._insert_audit_event(
                conn,
                "expense_template",
                template_id,
                "expense_created",
                payload,
            )

        return {
            "template_id": template_id,
            "name": payload["name"],
            "category": payload["category"],
            "recurrence": recurrence,
            "amount": amount,
        }

    def _archive_expense(self, template_id: str) -> dict[str, Any]:
        now = _utcnow()

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT template_id, name, category, recurrence, is_active
                FROM expense_templates
                WHERE template_id = ?
                """,
                (template_id,),
            ).fetchone()
            if row is None:
                raise HomeAssistantError(f"Unknown template_id: {template_id}")

            conn.execute(
                """
                UPDATE expense_templates
                SET is_active = 0, updated_at = ?
                WHERE template_id = ?
                """,
                (now, template_id),
            )
            self._insert_audit_event(
                conn,
                "expense_template",
                template_id,
                "expense_archived",
                {"was_active": bool(row["is_active"])},
            )

        return {
            "template_id": template_id,
            "name": row["name"],
            "category": row["category"],
            "recurrence": row["recurrence"],
            "is_active": False,
        }

    def _copy_year(self, source_year: int, target_year: int) -> dict[str, Any]:
        if source_year == target_year:
            raise HomeAssistantError("source_year and target_year must be different")
        if source_year < 2000 or source_year > 2100:
            raise HomeAssistantError("source_year must be between 2000 and 2100")
        if target_year < 2000 or target_year > 2100:
            raise HomeAssistantError("target_year must be between 2000 and 2100")

        now = _utcnow()
        created_entries = 0

        with self._connect() as conn:
            source_plan = conn.execute(
                """
                SELECT year_plan_id, status
                FROM year_plans
                WHERE plan_year = ?
                """,
                (source_year,),
            ).fetchone()
            if source_plan is None:
                raise HomeAssistantError(f"Unknown source_year: {source_year}")

            target_plan = conn.execute(
                """
                SELECT year_plan_id, status
                FROM year_plans
                WHERE plan_year = ?
                """,
                (target_year,),
            ).fetchone()

            if target_plan is None:
                target_plan_id = uuid4().hex
                conn.execute(
                    """
                    INSERT INTO year_plans (
                        year_plan_id, plan_year, status, source_year, created_at, activated_at
                    ) VALUES (?, ?, 'draft', ?, ?, NULL)
                    """,
                    (target_plan_id, target_year, source_year, now),
                )
            else:
                target_plan_id = target_plan["year_plan_id"]
                if target_plan["status"] == "active":
                    raise HomeAssistantError(
                        f"Year {target_year} is already active and cannot be overwritten"
                    )
                self._delete_plan_rows(conn, target_plan_id)
                conn.execute(
                    """
                    UPDATE year_plans
                    SET status = 'draft', source_year = ?, activated_at = NULL
                    WHERE year_plan_id = ?
                    """,
                    (source_year, target_plan_id),
                )

            source_rows = conn.execute(
                """
                SELECT
                    ypi.template_id,
                    ypi.month_number,
                    ypi.scheduled_amount,
                    ypi.due_day,
                    me.name,
                    me.category,
                    me.icon,
                    me.notes
                FROM year_plan_items ypi
                LEFT JOIN month_entries me ON me.plan_item_id = ypi.plan_item_id
                WHERE ypi.year_plan_id = ?
                ORDER BY ypi.month_number, me.display_order, ypi.template_id
                """,
                (source_plan["year_plan_id"],),
            ).fetchall()
            if not source_rows:
                raise HomeAssistantError(
                    f"Year {source_year} does not have any plan items to copy"
                )

            for row in source_rows:
                due_day = _maybe_int(row["due_day"])
                due_date = _resolve_due_date(target_year, row["month_number"], due_day)
                display_order = row["month_number"] * 100 + (due_day or 99)
                plan_item_id = uuid4().hex
                entry_id = uuid4().hex

                conn.execute(
                    """
                    INSERT INTO year_plan_items (
                        plan_item_id, year_plan_id, template_id, month_number,
                        scheduled_amount, due_day, due_date, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        plan_item_id,
                        target_plan_id,
                        row["template_id"],
                        row["month_number"],
                        float(row["scheduled_amount"]),
                        due_day,
                        due_date,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO month_entries (
                        entry_id, plan_item_id, template_id, month_key, display_order,
                        name, category, icon, scheduled_amount, actual_paid_amount,
                        remaining_amount, due_date, status, notes, paid_date,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'pending', ?, NULL, ?, ?)
                    """,
                    (
                        entry_id,
                        plan_item_id,
                        row["template_id"],
                        f"{target_year:04d}-{row['month_number']:02d}",
                        display_order,
                        row["name"],
                        row["category"],
                        row["icon"],
                        float(row["scheduled_amount"]),
                        float(row["scheduled_amount"]),
                        due_date,
                        row["notes"],
                        now,
                        now,
                    ),
                )
                created_entries += 1

            self._insert_audit_event(
                conn,
                "year_plan",
                target_plan_id,
                "year_copied",
                {
                    "source_year": source_year,
                    "target_year": target_year,
                    "created_entries": created_entries,
                    "source_status": source_plan["status"],
                },
            )

        return {
            "source_year": source_year,
            "target_year": target_year,
            "created_entries": created_entries,
            "status": "draft",
        }

    def _update_expense(self, template_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        if not changes:
            raise HomeAssistantError("No changes were provided")

        allowed_fields = {
            "name": "name",
            "category": "category",
            "icon": "icon",
            "notes": "notes",
            "recurrence": "recurrence",
            "amount": "default_amount",
            "due_day": "due_day",
            "due_date": "due_date",
            "start_month": "start_month",
            "end_month": "end_month",
            "reminder_days": "reminder_days",
            "is_active": "is_active",
        }

        updates: list[str] = []
        values: list[Any] = []
        for service_field, db_field in allowed_fields.items():
            if service_field not in changes:
                continue

            value = changes[service_field]
            if service_field == "recurrence" and value not in RECURRENCE_TYPES:
                raise HomeAssistantError(f"Unsupported recurrence type: {value}")
            if service_field == "due_day" and value is not None and not 1 <= int(value) <= 31:
                raise HomeAssistantError("due_day must be between 1 and 31")
            if service_field == "amount" and value is not None:
                value = float(value)
            if service_field == "is_active":
                value = 1 if bool(value) else 0

            updates.append(f"{db_field} = ?")
            values.append(value)

        rule_fields = ("custom_months", "month_amount_overrides", "month_day_overrides")
        if not updates and not any(field in changes for field in rule_fields):
            raise HomeAssistantError("No supported fields were provided")

        now = _utcnow()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT template_id FROM expense_templates WHERE template_id = ?",
                (template_id,),
            ).fetchone()
            if existing is None:
                raise HomeAssistantError(f"Unknown template_id: {template_id}")

            if updates:
                values.extend([now, template_id])
                conn.execute(
                    f"""
                    UPDATE expense_templates
                    SET {", ".join(updates)}, updated_at = ?
                    WHERE template_id = ?
                    """,
                    values,
                )

            if any(field in changes for field in rule_fields):
                existing_rules = self._load_month_rules(conn).get(template_id, {})
                custom_months = (
                    self._parse_custom_months(changes.get("custom_months"))
                    if "custom_months" in changes
                    else sorted(existing_rules) or None
                )
                month_amount_overrides = (
                    self._normalize_month_mapping(changes.get("month_amount_overrides"))
                    if "month_amount_overrides" in changes
                    else {
                        str(month_number): row["amount_override"]
                        for month_number, row in existing_rules.items()
                        if row["amount_override"] is not None
                    }
                )
                month_day_overrides = (
                    self._normalize_month_mapping(changes.get("month_day_overrides"))
                    if "month_day_overrides" in changes
                    else {
                        str(month_number): row["day_override"]
                        for month_number, row in existing_rules.items()
                        if row["day_override"] is not None
                    }
                )
                self._replace_month_rules(
                    conn,
                    template_id,
                    custom_months,
                    month_amount_overrides,
                    month_day_overrides,
                )

            self._insert_audit_event(
                conn,
                "expense_template",
                template_id,
                "expense_updated",
                changes,
            )

            row = conn.execute(
                """
                SELECT template_id, name, category, recurrence, default_amount, due_day, is_active
                FROM expense_templates
                WHERE template_id = ?
                """,
                (template_id,),
            ).fetchone()

        return dict(row)

    def _generate_year(self, plan_year: int) -> dict[str, Any]:
        if plan_year < 2000 or plan_year > 2100:
            raise HomeAssistantError("year must be between 2000 and 2100")

        now = _utcnow()
        created_entries = 0
        created_templates = 0

        with self._connect() as conn:
            plan_row = conn.execute(
                "SELECT year_plan_id, status FROM year_plans WHERE plan_year = ?",
                (plan_year,),
            ).fetchone()

            if plan_row is None:
                year_plan_id = uuid4().hex
                conn.execute(
                    """
                    INSERT INTO year_plans (
                        year_plan_id, plan_year, status, source_year, created_at, activated_at
                    ) VALUES (?, ?, 'draft', NULL, ?, NULL)
                    """,
                    (year_plan_id, plan_year, now),
                )
            else:
                year_plan_id = plan_row["year_plan_id"]
                if plan_row["status"] == "active":
                    raise HomeAssistantError(
                        f"Year {plan_year} is already active and cannot be regenerated"
                    )
                self._delete_plan_rows(conn, year_plan_id)

            templates = conn.execute(
                """
                SELECT *
                FROM expense_templates
                WHERE is_active = 1
                ORDER BY category, name
                """
            ).fetchall()
            custom_rules = self._load_month_rules(conn)

            for template in templates:
                month_specs = self._expand_template_for_year(
                    plan_year, template, custom_rules.get(template["template_id"], {})
                )
                if not month_specs:
                    continue

                created_templates += 1
                for month_spec in month_specs:
                    plan_item_id = uuid4().hex
                    due_date = month_spec.due_date
                    status = "pending"
                    conn.execute(
                        """
                        INSERT INTO year_plan_items (
                            plan_item_id, year_plan_id, template_id, month_number,
                            scheduled_amount, due_day, due_date, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            plan_item_id,
                            year_plan_id,
                            template["template_id"],
                            month_spec.month_number,
                            month_spec.amount,
                            month_spec.due_day,
                            due_date,
                            status,
                            now,
                        ),
                    )

                    entry_id = uuid4().hex
                    conn.execute(
                        """
                        INSERT INTO month_entries (
                            entry_id, plan_item_id, template_id, month_key, display_order,
                            name, category, icon, scheduled_amount, actual_paid_amount,
                            remaining_amount, due_date, status, notes, paid_date,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, NULL, ?, ?)
                        """,
                        (
                            entry_id,
                            plan_item_id,
                            template["template_id"],
                            f"{plan_year:04d}-{month_spec.month_number:02d}",
                            month_spec.display_order,
                            template["name"],
                            template["category"],
                            template["icon"],
                            month_spec.amount,
                            month_spec.amount,
                            due_date,
                            status,
                            template["notes"],
                            now,
                            now,
                        ),
                    )
                    created_entries += 1

            self._insert_audit_event(
                conn,
                "year_plan",
                year_plan_id,
                "year_generated",
                {
                    "year": plan_year,
                    "created_entries": created_entries,
                    "templates_used": created_templates,
                },
            )

        return {
            "year": plan_year,
            "created_entries": created_entries,
            "templates_used": created_templates,
            "status": "draft",
        }

    def _activate_year(self, plan_year: int) -> dict[str, Any]:
        if plan_year < 2000 or plan_year > 2100:
            raise HomeAssistantError("year must be between 2000 and 2100")

        now = _utcnow()

        with self._connect() as conn:
            plan_row = conn.execute(
                """
                SELECT year_plan_id, status
                FROM year_plans
                WHERE plan_year = ?
                """,
                (plan_year,),
            ).fetchone()
            if plan_row is None:
                raise HomeAssistantError(f"Unknown year: {plan_year}")

            item_count = conn.execute(
                "SELECT COUNT(*) AS count FROM year_plan_items WHERE year_plan_id = ?",
                (plan_row["year_plan_id"],),
            ).fetchone()["count"]
            if item_count == 0:
                raise HomeAssistantError(
                    f"Year {plan_year} does not have any plan items to activate"
                )

            conn.execute(
                """
                UPDATE year_plans
                SET status = 'active', activated_at = ?
                WHERE year_plan_id = ?
                """,
                (now, plan_row["year_plan_id"]),
            )
            self._insert_audit_event(
                conn,
                "year_plan",
                plan_row["year_plan_id"],
                "year_activated",
                {"year": plan_year, "previous_status": plan_row["status"]},
            )

        return {
            "year": plan_year,
            "status": "active",
            "activated_at": now,
            "item_count": item_count,
        }

    def _delete_year_plan(self, plan_year: int) -> dict[str, Any]:
        if plan_year < 2000 or plan_year > 2100:
            raise HomeAssistantError("year must be between 2000 and 2100")

        with self._connect() as conn:
            plan_row = conn.execute(
                """
                SELECT year_plan_id, status
                FROM year_plans
                WHERE plan_year = ?
                """,
                (plan_year,),
            ).fetchone()
            if plan_row is None:
                raise HomeAssistantError(f"Unknown year: {plan_year}")

            entry_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM month_entries me
                JOIN year_plan_items ypi ON ypi.plan_item_id = me.plan_item_id
                WHERE ypi.year_plan_id = ?
                """,
                (plan_row["year_plan_id"],),
            ).fetchone()["count"]
            payment_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM payments p
                JOIN month_entries me ON me.entry_id = p.entry_id
                JOIN year_plan_items ypi ON ypi.plan_item_id = me.plan_item_id
                WHERE ypi.year_plan_id = ?
                """,
                (plan_row["year_plan_id"],),
            ).fetchone()["count"]
            self._insert_audit_event(
                conn,
                "year_plan",
                plan_row["year_plan_id"],
                "year_deleted",
                {
                    "year": plan_year,
                    "previous_status": plan_row["status"],
                    "deleted_entries": entry_count,
                    "deleted_payments": payment_count,
                },
            )
            conn.execute(
                "DELETE FROM year_plans WHERE year_plan_id = ?",
                (plan_row["year_plan_id"],),
            )

        return {
            "year": plan_year,
            "deleted_entries": entry_count,
            "deleted_payments": payment_count,
            "previous_status": plan_row["status"],
        }

    def _clear_reminder_log(self) -> dict[str, Any]:
        with self._connect() as conn:
            deleted = conn.execute(
                "SELECT COUNT(*) AS count FROM notifications_log"
            ).fetchone()["count"]
            conn.execute("DELETE FROM notifications_log")
            self._insert_audit_event(
                conn,
                "notifications_log",
                "all",
                "reminder_log_cleared",
                {"deleted_notifications": deleted},
            )

        return {"deleted_notifications": deleted}

    def _delete_month(self, month_key: str) -> dict[str, Any]:
        normalized_month = str(month_key or "").strip()
        if not _is_month_key(normalized_month):
            raise HomeAssistantError("month_key must use YYYY-MM format")

        with self._connect() as conn:
            entry_ids = [
                row["entry_id"]
                for row in conn.execute(
                    "SELECT entry_id FROM month_entries WHERE month_key = ?",
                    (normalized_month,),
                ).fetchall()
            ]
            if not entry_ids:
                raise HomeAssistantError(f"No generated month entries found for {normalized_month}")

            payment_count = self._delete_month_entries(conn, entry_ids)
            self._insert_audit_event(
                conn,
                "month_entries",
                normalized_month,
                "month_deleted",
                {
                    "month_key": normalized_month,
                    "deleted_entries": len(entry_ids),
                    "deleted_payments": payment_count,
                },
            )

        return {
            "month_key": normalized_month,
            "deleted_entries": len(entry_ids),
            "deleted_payments": payment_count,
        }

    def _generate_month(self, month_key: str) -> dict[str, Any]:
        normalized_month = str(month_key or "").strip()
        if not _is_month_key(normalized_month):
            raise HomeAssistantError("month_key must use YYYY-MM format")

        plan_year = int(normalized_month[:4])
        month_number = int(normalized_month[5:7])
        now = _utcnow()

        with self._connect() as conn:
            plan_row = conn.execute(
                """
                SELECT year_plan_id, status
                FROM year_plans
                WHERE plan_year = ?
                """,
                (plan_year,),
            ).fetchone()
            if plan_row is None:
                raise HomeAssistantError(
                    f"Generate year {plan_year} first, then generate {normalized_month}"
                )

            plan_items = conn.execute(
                """
                SELECT
                    ypi.plan_item_id,
                    ypi.template_id,
                    ypi.scheduled_amount,
                    ypi.due_day,
                    ypi.due_date,
                    et.name,
                    et.category,
                    et.icon,
                    et.notes
                FROM year_plan_items ypi
                JOIN expense_templates et ON et.template_id = ypi.template_id
                WHERE ypi.year_plan_id = ? AND ypi.month_number = ?
                ORDER BY ypi.due_date, ypi.template_id
                """,
                (plan_row["year_plan_id"], month_number),
            ).fetchall()
            if not plan_items:
                raise HomeAssistantError(
                    f"No plan rows found for {normalized_month}. Add/import expenses and generate {plan_year} first."
                )

            existing_entry_ids = [
                row["entry_id"]
                for row in conn.execute(
                    "SELECT entry_id FROM month_entries WHERE month_key = ?",
                    (normalized_month,),
                ).fetchall()
            ]
            deleted_payments = self._delete_month_entries(conn, existing_entry_ids)

            for item in plan_items:
                due_day = item["due_day"]
                amount = float(item["scheduled_amount"])
                status = _status_for_amounts(amount, 0.0)
                conn.execute(
                    """
                    INSERT INTO month_entries (
                        entry_id, plan_item_id, template_id, month_key, display_order,
                        name, category, icon, scheduled_amount, actual_paid_amount,
                        remaining_amount, due_date, status, notes, paid_date,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        item["plan_item_id"],
                        item["template_id"],
                        normalized_month,
                        _display_order_for_month_key(normalized_month, due_day),
                        item["name"],
                        item["category"],
                        item["icon"],
                        amount,
                        amount,
                        item["due_date"],
                        status,
                        item["notes"],
                        now,
                        now,
                    ),
                )

            self._insert_audit_event(
                conn,
                "month_entries",
                normalized_month,
                "month_generated",
                {
                    "month_key": normalized_month,
                    "year": plan_year,
                    "created_entries": len(plan_items),
                    "replaced_entries": len(existing_entry_ids),
                    "deleted_payments": deleted_payments,
                },
            )

        return {
            "month_key": normalized_month,
            "year": plan_year,
            "created_entries": len(plan_items),
            "replaced_entries": len(existing_entry_ids),
            "deleted_payments": deleted_payments,
            "plan_status": plan_row["status"],
        }

    def _reset_database(self) -> dict[str, Any]:
        tables = (
            "payments",
            "notifications_log",
            "month_entries",
            "year_plan_items",
            "year_plans",
            "template_month_rules",
            "expense_templates",
            "app_settings",
            "audit_events",
        )
        with self._connect() as conn:
            deleted_counts = {
                table: conn.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                ).fetchone()["count"]
                for table in tables
            }
            for table in tables:
                conn.execute(f"DELETE FROM {table}")

        return {"deleted_counts": deleted_counts}

    def _list_expenses(
        self, active_only: bool, category: str | None
    ) -> dict[str, Any]:
        query = """
            SELECT *
            FROM expense_templates
        """
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append("is_active = 1")
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY is_active DESC, category, name"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            rules_by_template = self._load_month_rules(conn)

        expenses = [
            self._serialize_expense_template(row, rules_by_template.get(row["template_id"], {}))
            for row in rows
        ]
        return {
            "count": len(expenses),
            "active_only": active_only,
            "category": category,
            "expenses": expenses,
        }

    def _get_current_month(
        self,
        month_key: str | None,
        status: str | None,
        category: str | None,
    ) -> dict[str, Any]:
        effective_month_key = month_key or _current_month_key()
        effective_status = status or None
        effective_category = category or None
        today = date.today().isoformat()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    me.entry_id,
                    me.plan_item_id,
                    me.template_id,
                    me.month_key,
                    me.display_order,
                    me.name,
                    me.category,
                    me.icon,
                    me.scheduled_amount,
                    me.actual_paid_amount,
                    me.remaining_amount,
                    me.due_date,
                    me.status,
                    me.notes,
                    me.paid_date,
                    (
                        SELECT p.payment_id
                        FROM payments p
                        WHERE p.entry_id = me.entry_id
                        ORDER BY p.paid_date DESC, p.created_at DESC
                        LIMIT 1
                    ) AS latest_payment_id,
                    (
                        SELECT p.amount
                        FROM payments p
                        WHERE p.entry_id = me.entry_id
                        ORDER BY p.paid_date DESC, p.created_at DESC
                        LIMIT 1
                    ) AS latest_payment_amount,
                    yp.plan_year,
                    yp.status AS plan_status
                FROM month_entries me
                JOIN year_plan_items ypi ON ypi.plan_item_id = me.plan_item_id
                JOIN year_plans yp ON yp.year_plan_id = ypi.year_plan_id
                WHERE me.month_key = ?
                ORDER BY me.display_order, me.name, me.entry_id
                """,
                (effective_month_key,),
            ).fetchall()

        entries = [self._serialize_month_entry(row, today) for row in rows]
        if effective_status:
            entries = [entry for entry in entries if entry["status"] == effective_status]
        if effective_category:
            entries = [entry for entry in entries if entry["category"] == effective_category]
        entries = [
            entry
            for _, entry in sorted(
                enumerate(entries),
                key=lambda indexed_entry: (
                    indexed_entry[1]["status"] == "paid",
                    indexed_entry[0],
                ),
            )
        ]

        summary = self._summarize_entries(entries)
        return {
            "month_key": effective_month_key,
            "status_filter": effective_status,
            "category_filter": effective_category,
            "entry_count": len(entries),
            "summary": summary,
            "entries": entries,
        }

    def _get_year_plan(self, plan_year: int, month: int | None) -> dict[str, Any]:
        if plan_year < 2000 or plan_year > 2100:
            raise HomeAssistantError("year must be between 2000 and 2100")
        if month is not None and (month < 1 or month > 12):
            raise HomeAssistantError("month must be between 1 and 12")

        today = date.today().isoformat()

        with self._connect() as conn:
            plan_row = conn.execute(
                """
                SELECT year_plan_id, plan_year, status, source_year, created_at, activated_at
                FROM year_plans
                WHERE plan_year = ?
                """,
                (plan_year,),
            ).fetchone()
            if plan_row is None:
                raise HomeAssistantError(f"Unknown year: {plan_year}")

            query = """
                SELECT
                    ypi.plan_item_id,
                    ypi.template_id,
                    ypi.month_number,
                    ypi.scheduled_amount,
                    ypi.due_day,
                    ypi.due_date,
                    ypi.status AS plan_item_status,
                    me.entry_id,
                    me.month_key,
                    me.display_order,
                    me.name,
                    me.category,
                    me.icon,
                    me.actual_paid_amount,
                    me.remaining_amount,
                    me.status,
                    me.notes,
                    me.paid_date
                FROM year_plan_items ypi
                LEFT JOIN month_entries me ON me.plan_item_id = ypi.plan_item_id
                WHERE ypi.year_plan_id = ?
            """
            params: list[Any] = [plan_row["year_plan_id"]]
            if month is not None:
                query += " AND ypi.month_number = ?"
                params.append(month)
            query += " ORDER BY ypi.month_number, me.display_order, me.name, ypi.plan_item_id"
            rows = conn.execute(query, params).fetchall()

        items = [self._serialize_year_plan_item(row, today, plan_year) for row in rows]
        monthly_rollups = self._summarize_year_plan_items(items)
        return {
            "year": plan_year,
            "month_filter": month,
            "plan": {
                "year_plan_id": plan_row["year_plan_id"],
                "status": plan_row["status"],
                "source_year": plan_row["source_year"],
                "created_at": plan_row["created_at"],
                "activated_at": plan_row["activated_at"],
            },
            "item_count": len(items),
            "summary": self._summarize_entries(items),
            "monthly_rollups": monthly_rollups,
            "items": items,
        }

    def _get_history(self, plan_year: int) -> dict[str, Any]:
        if plan_year < 2000 or plan_year > 2100:
            raise HomeAssistantError("year must be between 2000 and 2100")

        today = date.today().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    me.entry_id, me.plan_item_id, me.template_id, me.month_key,
                    me.display_order, me.name, me.category, me.icon,
                    me.scheduled_amount, me.actual_paid_amount, me.remaining_amount,
                    me.due_date, me.status, me.notes, me.paid_date,
                    yp.plan_year, yp.status AS plan_status
                FROM month_entries me
                JOIN year_plan_items ypi ON ypi.plan_item_id = me.plan_item_id
                JOIN year_plans yp ON yp.year_plan_id = ypi.year_plan_id
                WHERE yp.plan_year = ?
                ORDER BY me.month_key, me.display_order, me.name
                """,
                (plan_year,),
            ).fetchall()
            payment_rows = conn.execute(
                """
                SELECT
                    p.payment_id, p.entry_id, p.amount, p.paid_date, p.note,
                    p.created_at, me.name, me.category, me.month_key
                FROM payments p
                JOIN month_entries me ON me.entry_id = p.entry_id
                WHERE me.month_key LIKE ?
                ORDER BY p.paid_date DESC, p.created_at DESC
                """,
                (f"{plan_year:04d}-%",),
            ).fetchall()

        entries = [self._serialize_month_entry(row, today) for row in rows]
        monthly: list[dict[str, Any]] = []
        for month_number in range(1, 13):
            month_key = f"{plan_year:04d}-{month_number:02d}"
            month_entries = [entry for entry in entries if entry["month_key"] == month_key]
            monthly.append(
                {
                    "month": month_number,
                    "month_key": month_key,
                    "entry_count": len(month_entries),
                    "summary": self._summarize_entries(month_entries),
                    "entries": month_entries,
                }
            )

        summary = self._summarize_entries(entries)
        payments = [
            {
                "payment_id": row["payment_id"],
                "entry_id": row["entry_id"],
                "name": row["name"],
                "category": row["category"],
                "month_key": row["month_key"],
                "amount": float(row["amount"]),
                "paid_date": row["paid_date"],
                "note": row["note"],
                "created_at": row["created_at"],
            }
            for row in payment_rows
        ]
        return {
            "year": plan_year,
            "entry_count": len(entries),
            "summary": summary,
            "monthly": monthly,
            "payments": payments,
        }

    def _get_settings(self) -> dict[str, Any]:
        settings = dict(DEFAULT_SETTINGS)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT setting_key, value_json FROM app_settings"
            ).fetchall()
        for row in rows:
            if row["setting_key"] in settings:
                settings[row["setting_key"]] = json.loads(row["value_json"])
        return settings

    def _update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_SETTINGS)
        unsupported = set(changes) - allowed
        if unsupported:
            raise HomeAssistantError(
                f"Unsupported settings: {', '.join(sorted(unsupported))}"
            )

        normalized: dict[str, Any] = {}
        if "currency" in changes:
            currency = str(changes["currency"]).strip().upper()
            if len(currency) != 3 or not currency.isalpha():
                raise HomeAssistantError("currency must be a three-letter code")
            normalized["currency"] = currency
        if "reminders_enabled" in changes:
            normalized["reminders_enabled"] = bool(changes["reminders_enabled"])
        if "notification_service" in changes:
            notification_service = str(changes["notification_service"]).strip()
            parts = notification_service.split(".")
            if len(parts) != 2 or not all(parts):
                raise HomeAssistantError(
                    "notification_service must use domain.service format"
                )
            normalized["notification_service"] = notification_service
        if "scan_interval_minutes" in changes:
            interval = int(changes["scan_interval_minutes"])
            if interval < 5 or interval > 1440:
                raise HomeAssistantError(
                    "scan_interval_minutes must be between 5 and 1440"
                )
            normalized["scan_interval_minutes"] = interval

        now = _utcnow()
        with self._connect() as conn:
            for key, value in normalized.items():
                conn.execute(
                    """
                    INSERT INTO app_settings (setting_key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(value), now),
                )
            self._insert_audit_event(
                conn,
                "settings",
                "global",
                "settings_updated",
                normalized,
            )
        return self._get_settings()

    def _get_reminder_candidates(self, today: str | None) -> list[dict[str, Any]]:
        effective_today = date.fromisoformat(today) if today else date.today()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    me.entry_id, me.name, me.category, me.due_date,
                    me.remaining_amount, me.scheduled_amount, et.reminder_days
                FROM month_entries me
                JOIN expense_templates et ON et.template_id = me.template_id
                WHERE me.remaining_amount > 0 AND me.due_date IS NOT NULL
                ORDER BY me.due_date, me.display_order, me.name
                """
            ).fetchall()
            candidates = []
            for row in rows:
                due_date = date.fromisoformat(row["due_date"])
                days_until_due = (due_date - effective_today).days
                reminder_days = int(row["reminder_days"])
                if days_until_due > reminder_days or days_until_due < -30:
                    continue
                reminder_type = (
                    "overdue" if days_until_due < 0 else "due" if days_until_due == 0 else "upcoming"
                )
                dedupe_key = (
                    f"{row['entry_id']}:{reminder_type}:{effective_today.isoformat()}"
                )
                already_sent = conn.execute(
                    "SELECT 1 FROM notifications_log WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
                if already_sent:
                    continue
                candidates.append(
                    {
                        "entry_id": row["entry_id"],
                        "name": row["name"],
                        "category": row["category"],
                        "due_date": row["due_date"],
                        "remaining_amount": float(row["remaining_amount"]),
                        "scheduled_amount": float(row["scheduled_amount"]),
                        "days_until_due": days_until_due,
                        "reminder_type": reminder_type,
                        "dedupe_key": dedupe_key,
                    }
                )
        return candidates

    def _log_notification(
        self,
        entry_id: str,
        reminder_type: str,
        dedupe_key: str,
        channel: str,
        payload: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO notifications_log (
                    notification_id, entry_id, reminder_type, sent_at,
                    dedupe_key, channel, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    entry_id,
                    reminder_type,
                    _utcnow(),
                    dedupe_key,
                    channel,
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def _mark_paid(
        self, entry_id: str, amount: float, paid_date: str | None, note: str | None
    ) -> dict[str, Any]:
        return self._record_payment(entry_id, amount, paid_date, note)

    def _mark_partial(
        self, entry_id: str, amount: float, paid_date: str | None, note: str | None
    ) -> dict[str, Any]:
        return self._record_payment(entry_id, amount, paid_date, note)

    def _update_month_entry(self, entry_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        if not changes:
            raise HomeAssistantError("No changes were provided")

        allowed_fields = {
            "name": "name",
            "category": "category",
            "icon": "icon",
            "notes": "notes",
        }
        now = _utcnow()

        with self._connect() as conn:
            entry = conn.execute(
                """
                SELECT entry_id, plan_item_id, month_key
                FROM month_entries
                WHERE entry_id = ?
                """,
                (entry_id,),
            ).fetchone()
            if entry is None:
                raise HomeAssistantError(f"Unknown entry_id: {entry_id}")

            updates: list[str] = []
            values: list[Any] = []
            for service_field, db_field in allowed_fields.items():
                if service_field not in changes:
                    continue
                updates.append(f"{db_field} = ?")
                values.append(changes[service_field])

            if "due_date" in changes:
                due_date = _normalize_due_date_for_month(changes["due_date"], entry["month_key"])
                due_day = _month_day_from_due_date(due_date)
                updates.extend(["due_date = ?", "display_order = ?"])
                values.extend([
                    due_date,
                    _display_order_for_month_key(entry["month_key"], due_day),
                ])
                conn.execute(
                    """
                    UPDATE year_plan_items
                    SET due_date = ?, due_day = ?
                    WHERE plan_item_id = ?
                    """,
                    (due_date, due_day, entry["plan_item_id"]),
                )

            if "scheduled_amount" in changes:
                scheduled_amount = float(changes["scheduled_amount"])
                if scheduled_amount < 0:
                    raise HomeAssistantError("scheduled_amount must be zero or greater")
                updates.append("scheduled_amount = ?")
                values.append(scheduled_amount)
                conn.execute(
                    """
                    UPDATE year_plan_items
                    SET scheduled_amount = ?
                    WHERE plan_item_id = ?
                    """,
                    (scheduled_amount, entry["plan_item_id"]),
                )

            if not updates:
                raise HomeAssistantError("No supported fields were provided")

            values.extend([now, entry_id])
            conn.execute(
                f"""
                UPDATE month_entries
                SET {", ".join(updates)}, updated_at = ?
                WHERE entry_id = ?
                """,
                values,
            )

            balances = (
                self._refresh_month_entry_balances(conn, entry_id)
                if "scheduled_amount" in changes
                else self._month_entry_balance_payload(conn, entry_id)
            )
            self._insert_audit_event(
                conn,
                "month_entry",
                entry_id,
                "month_entry_updated",
                changes,
            )
            response_row = self._fetch_month_entry_row(conn, entry_id)

        return {
            "entry": self._serialize_month_entry(response_row, date.today().isoformat()),
            **balances,
        }

    def _undo_payment(self, payment_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            payment = conn.execute(
                """
                SELECT payment_id, entry_id, amount, paid_date, note
                FROM payments
                WHERE payment_id = ?
                """,
                (payment_id,),
            ).fetchone()
            if payment is None:
                raise HomeAssistantError(f"Unknown payment_id: {payment_id}")

            conn.execute("DELETE FROM payments WHERE payment_id = ?", (payment_id,))
            balances = self._refresh_month_entry_balances(conn, payment["entry_id"])
            self._insert_audit_event(
                conn,
                "month_entry",
                payment["entry_id"],
                "payment_undone",
                {
                    "payment_id": payment_id,
                    "amount": float(payment["amount"]),
                    "paid_date": payment["paid_date"],
                    "note": payment["note"],
                },
            )
            response_row = self._fetch_month_entry_row(conn, payment["entry_id"])

        return {
            "entry_id": payment["entry_id"],
            "removed_payment_id": payment_id,
            "entry": self._serialize_month_entry(response_row, date.today().isoformat()),
            **balances,
        }

    def _record_payment(
        self, entry_id: str, amount: float, paid_date: str | None, note: str | None
    ) -> dict[str, Any]:
        if amount <= 0:
            raise HomeAssistantError("amount must be greater than zero")

        effective_paid_date = _normalize_iso_date(paid_date) if paid_date else date.today().isoformat()
        now = _utcnow()

        with self._connect() as conn:
            entry = conn.execute(
                "SELECT entry_id FROM month_entries WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if entry is None:
                raise HomeAssistantError(f"Unknown entry_id: {entry_id}")

            payment_id = uuid4().hex
            conn.execute(
                """
                INSERT INTO payments (payment_id, entry_id, amount, paid_date, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (payment_id, entry_id, amount, effective_paid_date, note, now),
            )
            balances = self._refresh_month_entry_balances(conn, entry_id)
            self._insert_audit_event(
                conn,
                "month_entry",
                entry_id,
                "payment_recorded",
                {
                    "payment_id": payment_id,
                    "amount": amount,
                    "paid_date": effective_paid_date,
                    "note": note,
                },
            )

        return {
            "entry_id": entry_id,
            "payment_id": payment_id,
            **balances,
        }

    def _refresh_month_entry_balances(
        self, conn: sqlite3.Connection, entry_id: str
    ) -> dict[str, Any]:
        entry = conn.execute(
            "SELECT scheduled_amount FROM month_entries WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
        if entry is None:
            raise HomeAssistantError(f"Unknown entry_id: {entry_id}")

        totals = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS actual_paid_amount, MAX(paid_date) AS paid_date
            FROM payments
            WHERE entry_id = ?
            """,
            (entry_id,),
        ).fetchone()
        scheduled_amount = float(entry["scheduled_amount"])
        actual_paid_amount = round(float(totals["actual_paid_amount"]), 2)
        remaining_amount = max(0.0, round(scheduled_amount - actual_paid_amount, 2))
        status = _status_for_amounts(scheduled_amount, actual_paid_amount)
        paid_date = totals["paid_date"] if actual_paid_amount > 0 else None

        conn.execute(
            """
            UPDATE month_entries
            SET actual_paid_amount = ?, remaining_amount = ?, status = ?, paid_date = ?, updated_at = ?
            WHERE entry_id = ?
            """,
            (actual_paid_amount, remaining_amount, status, paid_date, _utcnow(), entry_id),
        )
        return {
            "actual_paid_amount": actual_paid_amount,
            "remaining_amount": remaining_amount,
            "status": status,
            "paid_date": paid_date,
        }

    def _month_entry_balance_payload(
        self, conn: sqlite3.Connection, entry_id: str
    ) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT actual_paid_amount, remaining_amount, status, paid_date
            FROM month_entries
            WHERE entry_id = ?
            """,
            (entry_id,),
        ).fetchone()
        if row is None:
            raise HomeAssistantError(f"Unknown entry_id: {entry_id}")
        return {
            "actual_paid_amount": float(row["actual_paid_amount"]),
            "remaining_amount": float(row["remaining_amount"]),
            "status": row["status"],
            "paid_date": row["paid_date"],
        }

    def _fetch_month_entry_row(
        self, conn: sqlite3.Connection, entry_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT
                me.entry_id,
                me.plan_item_id,
                me.template_id,
                me.month_key,
                me.display_order,
                me.name,
                me.category,
                me.icon,
                me.scheduled_amount,
                me.actual_paid_amount,
                me.remaining_amount,
                me.due_date,
                me.status,
                me.notes,
                me.paid_date,
                yp.plan_year,
                yp.status AS plan_status
            FROM month_entries me
            JOIN year_plan_items ypi ON ypi.plan_item_id = me.plan_item_id
            JOIN year_plans yp ON yp.year_plan_id = ypi.year_plan_id
            WHERE me.entry_id = ?
            """,
            (entry_id,),
        ).fetchone()
        if row is None:
            raise HomeAssistantError(f"Unknown entry_id: {entry_id}")
        return row

    def _replace_month_rules(
        self,
        conn: sqlite3.Connection,
        template_id: str,
        custom_months: Sequence[int] | None,
        month_amount_overrides: Mapping[str, Any] | None,
        month_day_overrides: Mapping[str, Any] | None,
    ) -> None:
        if (
            custom_months is None
            and month_amount_overrides is None
            and month_day_overrides is None
        ):
            return

        normalized_amounts = self._normalize_month_mapping(month_amount_overrides)
        normalized_days = self._normalize_month_mapping(month_day_overrides)

        conn.execute(
            "DELETE FROM template_month_rules WHERE template_id = ?",
            (template_id,),
        )

        month_numbers = set(custom_months or [])
        month_numbers.update(int(month) for month in (normalized_amounts or {}))
        month_numbers.update(int(month) for month in (normalized_days or {}))

        now = _utcnow()
        for month_number in sorted(month_numbers):
            conn.execute(
                """
                INSERT INTO template_month_rules (
                    rule_id, template_id, month_number, amount_override, day_override,
                    month_date_override, created_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    uuid4().hex,
                    template_id,
                    month_number,
                    _maybe_float((normalized_amounts or {}).get(str(month_number))),
                    _maybe_int((normalized_days or {}).get(str(month_number))),
                    now,
                ),
            )

    def _parse_custom_months(self, value: Any) -> list[int] | None:
        if value in (None, "", []):
            return None
        if isinstance(value, str):
            months = [part.strip() for part in value.split(",") if part.strip()]
        else:
            months = list(value)

        parsed = sorted({int(month) for month in months})
        if any(month < 1 or month > 12 for month in parsed):
            raise HomeAssistantError("custom_months values must be between 1 and 12")
        return parsed

    def _normalize_month_mapping(
        self, value: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is None:
            return None

        normalized: dict[str, Any] = {}
        for month_key, month_value in value.items():
            month_number = int(month_key)
            if month_number < 1 or month_number > 12:
                raise HomeAssistantError("Month override keys must be between 1 and 12")
            normalized[str(month_number)] = month_value
        return normalized

    def _load_month_rules(
        self, conn: sqlite3.Connection
    ) -> dict[str, dict[int, sqlite3.Row]]:
        rows = conn.execute(
            """
            SELECT template_id, month_number, amount_override, day_override, month_date_override
            FROM template_month_rules
            """
        ).fetchall()
        grouped: dict[str, dict[int, sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row["template_id"], {})[row["month_number"]] = row
        return grouped

    def _expand_template_for_year(
        self,
        plan_year: int,
        template: sqlite3.Row,
        rules: Mapping[int, sqlite3.Row],
    ) -> list[_MonthSpec]:
        months = self._months_for_template(template, rules)
        specs: list[_MonthSpec] = []
        for month_number in months:
            rule = rules.get(month_number)
            amount = (
                float(rule["amount_override"])
                if rule and rule["amount_override"] is not None
                else float(template["default_amount"])
            )
            due_day = (
                int(rule["day_override"])
                if rule and rule["day_override"] is not None
                else _maybe_int(template["due_day"])
            )
            due_date = _resolve_due_date(plan_year, month_number, due_day)
            display_order = month_number * 100 + (due_day or 99)
            specs.append(
                _MonthSpec(
                    month_number=month_number,
                    amount=amount,
                    due_day=due_day,
                    due_date=due_date,
                    display_order=display_order,
                )
            )
        return specs

    def _months_for_template(
        self,
        template: sqlite3.Row,
        rules: Mapping[int, sqlite3.Row],
    ) -> list[int]:
        recurrence = template["recurrence"]
        start_month = _month_from_value(template["start_month"])
        end_month = _month_from_value(template["end_month"])

        if recurrence == "monthly":
            months = list(range(1, 13))
        elif recurrence == "annual":
            months = [start_month or 1]
        elif recurrence == "twice_yearly":
            if rules:
                months = sorted(rules)
            else:
                first = start_month or 1
                second = ((first + 5) % 12) + 1
                months = sorted({first, second})
        elif recurrence == "custom_months":
            months = sorted(rules)
        elif recurrence == "one_time":
            months = [start_month or _month_from_value(template["due_date"]) or 1]
        else:
            raise HomeAssistantError(f"Unsupported recurrence type: {recurrence}")

        if start_month is not None:
            months = [month for month in months if month >= start_month]
        if end_month is not None:
            months = [month for month in months if month <= end_month]
        return months

    def _delete_plan_rows(self, conn: sqlite3.Connection, year_plan_id: str) -> None:
        plan_item_ids = [
            row["plan_item_id"]
            for row in conn.execute(
                "SELECT plan_item_id FROM year_plan_items WHERE year_plan_id = ?",
                (year_plan_id,),
            ).fetchall()
        ]
        if plan_item_ids:
            entry_ids = [
                row["entry_id"]
                for row in conn.execute(
                    f"""
                    SELECT entry_id
                    FROM month_entries
                    WHERE plan_item_id IN ({','.join('?' for _ in plan_item_ids)})
                    """,
                    plan_item_ids,
                ).fetchall()
            ]
            if entry_ids:
                conn.execute(
                    f"DELETE FROM payments WHERE entry_id IN ({','.join('?' for _ in entry_ids)})",
                    entry_ids,
                )
                conn.execute(
                    f"DELETE FROM month_entries WHERE entry_id IN ({','.join('?' for _ in entry_ids)})",
                    entry_ids,
                )

            conn.execute(
                f"DELETE FROM year_plan_items WHERE plan_item_id IN ({','.join('?' for _ in plan_item_ids)})",
                plan_item_ids,
            )

    def _delete_month_entries(self, conn: sqlite3.Connection, entry_ids: Sequence[str]) -> int:
        if not entry_ids:
            return 0

        placeholders = ",".join("?" for _ in entry_ids)
        payment_count = conn.execute(
            f"SELECT COUNT(*) AS count FROM payments WHERE entry_id IN ({placeholders})",
            list(entry_ids),
        ).fetchone()["count"]
        conn.execute(
            f"DELETE FROM notifications_log WHERE entry_id IN ({placeholders})",
            list(entry_ids),
        )
        conn.execute(
            f"DELETE FROM payments WHERE entry_id IN ({placeholders})",
            list(entry_ids),
        )
        conn.execute(
            f"DELETE FROM month_entries WHERE entry_id IN ({placeholders})",
            list(entry_ids),
        )
        return int(payment_count)

    def _serialize_expense_template(
        self,
        row: sqlite3.Row,
        rules: Mapping[int, sqlite3.Row],
    ) -> dict[str, Any]:
        month_rules = []
        custom_months: list[int] = []
        for month_number, rule in sorted(rules.items()):
            custom_months.append(month_number)
            month_rules.append(
                {
                    "month": month_number,
                    "amount_override": _maybe_float(rule["amount_override"]),
                    "day_override": _maybe_int(rule["day_override"]),
                }
            )

        return {
            "template_id": row["template_id"],
            "name": row["name"],
            "category": row["category"],
            "icon": row["icon"],
            "notes": row["notes"],
            "recurrence": row["recurrence"],
            "default_amount": float(row["default_amount"]),
            "due_day": _maybe_int(row["due_day"]),
            "due_date": row["due_date"],
            "start_month": _month_from_value(row["start_month"]),
            "end_month": _month_from_value(row["end_month"]),
            "reminder_days": int(row["reminder_days"]),
            "is_active": bool(row["is_active"]),
            "custom_months": custom_months,
            "month_rules": month_rules,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _serialize_month_entry(self, row: sqlite3.Row, today: str) -> dict[str, Any]:
        status = _derive_entry_status(row["status"], row["due_date"], today)
        has_latest_payment = "latest_payment_id" in row.keys()
        return {
            "entry_id": row["entry_id"],
            "plan_item_id": row["plan_item_id"],
            "template_id": row["template_id"],
            "month_key": row["month_key"],
            "name": row["name"],
            "category": row["category"],
            "icon": row["icon"],
            "scheduled_amount": float(row["scheduled_amount"]),
            "actual_paid_amount": float(row["actual_paid_amount"]),
            "remaining_amount": float(row["remaining_amount"]),
            "due_date": row["due_date"],
            "status": status,
            "stored_status": row["status"],
            "notes": row["notes"],
            "paid_date": row["paid_date"],
            "latest_payment_id": row["latest_payment_id"] if has_latest_payment else None,
            "latest_payment_amount": (
                _maybe_float(row["latest_payment_amount"]) if has_latest_payment else None
            ),
            "is_overdue": status == "overdue",
            "plan_year": row["plan_year"],
            "plan_status": row["plan_status"],
        }

    def _serialize_year_plan_item(
        self, row: sqlite3.Row, today: str, plan_year: int
    ) -> dict[str, Any]:
        status = _derive_entry_status(
            row["status"] or row["plan_item_status"], row["due_date"], today
        )
        month_key = row["month_key"] or f"{plan_year:04d}-{int(row['month_number']):02d}"
        return {
            "plan_item_id": row["plan_item_id"],
            "entry_id": row["entry_id"],
            "template_id": row["template_id"],
            "month_number": int(row["month_number"]),
            "month_key": month_key,
            "name": row["name"],
            "category": row["category"],
            "icon": row["icon"],
            "scheduled_amount": float(row["scheduled_amount"]),
            "actual_paid_amount": float(row["actual_paid_amount"] or 0),
            "remaining_amount": float(row["remaining_amount"] or row["scheduled_amount"]),
            "due_day": _maybe_int(row["due_day"]),
            "due_date": row["due_date"],
            "status": status,
            "stored_status": row["status"] or row["plan_item_status"],
            "notes": row["notes"],
            "paid_date": row["paid_date"],
        }

    def _summarize_entries(self, entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        status_counts = {key: 0 for key in ("pending", "partial", "paid", "overdue")}
        category_totals: dict[str, dict[str, float]] = {}
        scheduled_total = 0.0
        actual_paid_total = 0.0
        remaining_total = 0.0

        for entry in entries:
            status = str(entry["status"])
            if status not in status_counts:
                status_counts[status] = 0
            status_counts[status] += 1

            scheduled = float(entry["scheduled_amount"])
            actual = float(entry["actual_paid_amount"])
            remaining = float(entry["remaining_amount"])
            scheduled_total += scheduled
            actual_paid_total += actual
            remaining_total += remaining

            category = str(entry["category"])
            bucket = category_totals.setdefault(
                category,
                {"scheduled_amount": 0.0, "actual_paid_amount": 0.0, "remaining_amount": 0.0},
            )
            bucket["scheduled_amount"] += scheduled
            bucket["actual_paid_amount"] += actual
            bucket["remaining_amount"] += remaining

        return {
            "scheduled_total": round(scheduled_total, 2),
            "actual_paid_total": round(actual_paid_total, 2),
            "remaining_total": round(remaining_total, 2),
            "status_counts": status_counts,
            "category_totals": [
                {
                    "category": category,
                    "scheduled_amount": round(values["scheduled_amount"], 2),
                    "actual_paid_amount": round(values["actual_paid_amount"], 2),
                    "remaining_amount": round(values["remaining_amount"], 2),
                }
                for category, values in sorted(category_totals.items())
            ],
        }

    def _summarize_year_plan_items(
        self, items: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        by_month: dict[int, list[Mapping[str, Any]]] = {}
        for item in items:
            by_month.setdefault(int(item["month_number"]), []).append(item)

        rollups = []
        for month_number in sorted(by_month):
            month_items = by_month[month_number]
            summary = self._summarize_entries(month_items)
            rollups.append(
                {
                    "month_number": month_number,
                    "month_key": month_items[0]["month_key"],
                    "item_count": len(month_items),
                    **summary,
                }
            )
        return rollups

    def _insert_audit_event(
        self,
        conn: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_events (
                event_id, entity_type, entity_id, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                entity_type,
                entity_id,
                event_type,
                json.dumps(payload or {}, sort_keys=True),
                _utcnow(),
            ),
        )


@dataclass(slots=True)
class _MonthSpec:
    month_number: int
    amount: float
    due_day: int | None
    due_date: str | None
    display_order: int


def _resolve_due_date(plan_year: int, month_number: int, due_day: int | None) -> str | None:
    if due_day is None:
        return None
    _, max_day = monthrange(plan_year, month_number)
    return date(plan_year, month_number, min(due_day, max_day)).isoformat()


def _month_from_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if len(value) == 7 and value[4] == "-":
            return int(value[5:7])
        return int(value)
    raise HomeAssistantError(f"Unsupported month value: {value!r}")


def _maybe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _maybe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _current_month_key() -> str:
    return date.today().strftime("%Y-%m")


def _is_month_key(value: str) -> bool:
    if len(value) != 7 or value[4] != "-":
        return False
    try:
        year = int(value[:4])
        month = int(value[5:7])
    except ValueError:
        return False
    return 2000 <= year <= 2100 and 1 <= month <= 12


def _normalize_iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as err:
        raise HomeAssistantError(f"Invalid ISO date: {value}") from err


def _normalize_due_date_for_month(value: str | None, month_key: str) -> str | None:
    if value in (None, ""):
        return None
    normalized = _normalize_iso_date(value)
    if not normalized.startswith(f"{month_key}-"):
        raise HomeAssistantError(f"due_date must stay within month {month_key}")
    return normalized


def _month_day_from_due_date(value: str | None) -> int | None:
    if value is None:
        return None
    return date.fromisoformat(value).day


def _display_order_for_month_key(month_key: str, due_day: int | None) -> int:
    month_number = int(month_key[5:7])
    return month_number * 100 + (due_day or 99)


def _status_for_amounts(scheduled_amount: float, actual_paid_amount: float) -> str:
    if scheduled_amount <= 0 or actual_paid_amount >= scheduled_amount:
        return "paid"
    if actual_paid_amount <= 0:
        return "pending"
    return "partial"


def _derive_entry_status(stored_status: str | None, due_date: str | None, today: str) -> str:
    status = stored_status or "pending"
    if status in {"pending", "partial"} and due_date is not None and due_date < today:
        return "overdue"
    return status


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()
