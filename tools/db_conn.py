"""
tools/db_conn.py
PostgreSQL connection utility. All pipeline modules import get_conn from here.

Requires DATABASE_URL in your .env:
    postgresql://user:password@host:5432/dbname
"""

import os
from typing import Optional

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")


class _Conn:
    """
    Thin psycopg2 wrapper that exposes execute/fetchone/fetchall and acts as
    a context manager — commits on clean exit, rolls back on exception.
    """

    def __init__(self, raw: "psycopg2.extensions.connection"):
        self._raw = raw
        self._cur = raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql: str, params=None) -> "_Conn":
        self._cur.execute(sql, params or ())
        return self

    def executescript(self, sql: str) -> "_Conn":
        """Run multiple semicolon-separated DDL statements."""
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._cur.execute(stmt)
        return self

    def fetchone(self) -> Optional[dict]:
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self) -> list[dict]:
        return [dict(r) for r in self._cur.fetchall()]

    def __enter__(self) -> "_Conn":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            if exc_type:
                self._raw.rollback()
            else:
                self._raw.commit()
        finally:
            self._cur.close()
            self._raw.close()
        return False


def get_conn() -> _Conn:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Add it to your .env: postgresql://user:pass@host/dbname"
        )
    last_err = None
    for attempt in range(2):
        try:
            raw = psycopg2.connect(DATABASE_URL, connect_timeout=10)
            return _Conn(raw)
        except psycopg2.OperationalError as e:
            last_err = e
            if attempt == 0:
                import time
                time.sleep(3)
    raise last_err
