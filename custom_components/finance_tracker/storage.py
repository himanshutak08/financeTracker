"""SQLite-backed storage for the Finance Tracker integration."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
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
"""

RECURRENCE_TYPES = {
    "monthly",
    "one_time",
    "annual",
    "twice_yearly",
    "custom_months",
}


@dataclass(slots=True)
class FinanceTrackerStorage:
    """Persist finance data in SQLite."""

    hass: HomeAssistant
    _db_path: Path = field(init=False)

    def __post_init__(self) -> None:
        """Compute database path after dataclass initialization."""
        self._db_path = Path(self.hass.config.path(DB_RELATIVE_PATH))

    async def async_initialize(self) -> None:
        """Create database schema if needed."""
        await self.hass.async_add_executor_job(self._initialize_db)

    async def async_add_expense(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Create an expense template and any custom month rules."""
        return await self.hass.async_add_executor_job(self._add_expense, dict(payload))

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

    async def async_mark_paid(
        self, entry_id: str, amount: float, paid_date: str | None, note: str | None
    ) -> dict[str, Any]:
        """Record a payment against a month entry."""
        return await self.hass.async_add_executor_job(
            self._mark_paid, entry_id, amount, paid_date, note
        )

    def _initialize_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

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
                payload.get("month_amount_overrides"),
                payload.get("month_day_overrides"),
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

        if not updates and not any(
            field in changes for field in ("custom_months", "month_amount_overrides", "month_day_overrides")
        ):
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

            if any(
                field in changes for field in ("custom_months", "month_amount_overrides", "month_day_overrides")
            ):
                custom_months = self._parse_custom_months(changes.get("custom_months"))
                self._replace_month_rules(
                    conn,
                    template_id,
                    custom_months,
                    changes.get("month_amount_overrides"),
                    changes.get("month_day_overrides"),
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

    def _mark_paid(
        self, entry_id: str, amount: float, paid_date: str | None, note: str | None
    ) -> dict[str, Any]:
        if amount <= 0:
            raise HomeAssistantError("amount must be greater than zero")

        effective_paid_date = paid_date or date.today().isoformat()
        now = _utcnow()

        with self._connect() as conn:
            entry = conn.execute(
                """
                SELECT entry_id, scheduled_amount, actual_paid_amount, remaining_amount, status
                FROM month_entries
                WHERE entry_id = ?
                """,
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

            actual_paid_amount = float(entry["actual_paid_amount"]) + amount
            scheduled_amount = float(entry["scheduled_amount"])
            remaining_amount = max(0.0, round(scheduled_amount - actual_paid_amount, 2))
            status = "paid" if remaining_amount == 0 else "partial"

            conn.execute(
                """
                UPDATE month_entries
                SET actual_paid_amount = ?, remaining_amount = ?, status = ?,
                    paid_date = ?, updated_at = ?
                WHERE entry_id = ?
                """,
                (
                    actual_paid_amount,
                    remaining_amount,
                    status,
                    effective_paid_date,
                    now,
                    entry_id,
                ),
            )
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
            "actual_paid_amount": actual_paid_amount,
            "remaining_amount": remaining_amount,
            "status": status,
        }

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

        conn.execute(
            "DELETE FROM template_month_rules WHERE template_id = ?",
            (template_id,),
        )

        month_numbers = set(custom_months or [])
        month_numbers.update(int(month) for month in (month_amount_overrides or {}))
        month_numbers.update(int(month) for month in (month_day_overrides or {}))

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
                    _maybe_float((month_amount_overrides or {}).get(str(month_number))),
                    _maybe_int((month_day_overrides or {}).get(str(month_number))),
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
    ) -> list["_MonthSpec"]:
        months = self._months_for_template(template, rules)
        specs: list[_MonthSpec] = []
        for month_number in months:
            rule = rules.get(month_number)
            amount = float(rule["amount_override"]) if rule and rule["amount_override"] is not None else float(template["default_amount"])
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


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()
