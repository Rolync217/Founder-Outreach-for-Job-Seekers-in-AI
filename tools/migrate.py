"""
tools/migrate.py
Run all SQL migrations in order against DATABASE_URL.

Usage:
    python tools/migrate.py

Requires DATABASE_URL in your .env (loaded automatically).
"""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional — DATABASE_URL can be set in the environment directly

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("Error: DATABASE_URL is not set.", file=sys.stderr)
    print("Add it to your .env: postgresql://user:pass@host:5432/dbname", file=sys.stderr)
    sys.exit(1)

migrations_dir = Path(__file__).parent.parent / "migrations"
sql_files = sorted(migrations_dir.glob("*.sql"))

if not sql_files:
    print("No migration files found in migrations/")
    sys.exit(0)

conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
conn.autocommit = True
cur = conn.cursor()

for sql_file in sql_files:
    print(f"Running {sql_file.name} ...", end=" ", flush=True)
    cur.execute(sql_file.read_text())
    print("done")

cur.close()
conn.close()
print("All migrations applied.")
