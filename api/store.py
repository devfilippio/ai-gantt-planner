from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from typing import Protocol

from api.models import Plan
from api.seed import seed_plan

_SINGLETON_ID = 1


class Store(Protocol):
    def get_plan(self) -> Plan: ...

    def save_plan(self, plan: Plan) -> None: ...

    def snapshot(self) -> None: ...

    def undo(self) -> None: ...

    def reset_to_seed(self) -> None: ...


class MemoryStore:
    """In-memory implementation of Store. State lives on the instance so tests
    can create isolated stores, while `get_store()` hands out a shared
    module-level singleton for the running app/process."""

    def __init__(self) -> None:
        self._state: dict[str, Plan] = {}
        self._snapshots: list[Plan] = []

    def get_plan(self) -> Plan:
        plan = self._state.get("plan")
        if plan is None:
            plan = seed_plan()
            self._state["plan"] = plan
        return plan

    def save_plan(self, plan: Plan) -> None:
        self._state["plan"] = plan

    def snapshot(self) -> None:
        self._snapshots.append(copy.deepcopy(self.get_plan()))

    def undo(self) -> None:
        if not self._snapshots:
            return
        self._state["plan"] = self._snapshots.pop()

    def reset_to_seed(self) -> None:
        self._state["plan"] = seed_plan()
        self._snapshots = []


class PostgresStore:
    """Postgres-backed implementation of Store using psycopg, reading
    DATABASE_URL. Tables: plan_state(id, json), plan_snapshots(id, json, created_at).
    Not unit-tested; covered by manual/staging verification."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._ensure_schema()

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS plan_state (
                        id INTEGER PRIMARY KEY,
                        json JSONB NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS plan_snapshots (
                        id SERIAL PRIMARY KEY,
                        json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            conn.commit()

    def get_plan(self) -> Plan:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT json FROM plan_state WHERE id = %s", (_SINGLETON_ID,))
                row = cur.fetchone()
        if row is None:
            plan = seed_plan()
            self.save_plan(plan)
            return plan
        return Plan.model_validate(row[0])

    def save_plan(self, plan: Plan) -> None:
        payload = plan.model_dump_json()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO plan_state (id, json) VALUES (%s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET json = EXCLUDED.json
                    """,
                    (_SINGLETON_ID, payload),
                )
            conn.commit()

    def snapshot(self) -> None:
        plan = self.get_plan()
        payload = plan.model_dump_json()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO plan_snapshots (json, created_at) VALUES (%s::jsonb, %s)",
                    (payload, datetime.now(timezone.utc)),
                )
            conn.commit()

    def undo(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, json FROM plan_snapshots ORDER BY created_at DESC, id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row is None:
                    return
                snap_id, snap_json = row
                cur.execute(
                    """
                    INSERT INTO plan_state (id, json) VALUES (%s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET json = EXCLUDED.json
                    """,
                    (_SINGLETON_ID, snap_json),
                )
                cur.execute("DELETE FROM plan_snapshots WHERE id = %s", (snap_id,))
            conn.commit()

    def reset_to_seed(self) -> None:
        plan = seed_plan()
        self.save_plan(plan)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM plan_snapshots")
            conn.commit()


_store_singleton: Store | None = None


def get_store() -> Store:
    """Returns a single shared Store instance for the process (module-level
    singleton), so REST endpoints and the app share the same state."""
    global _store_singleton
    if _store_singleton is None:
        dsn = os.getenv("DATABASE_URL")
        _store_singleton = PostgresStore(dsn) if dsn else MemoryStore()
    return _store_singleton
