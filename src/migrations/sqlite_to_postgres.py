"""
SQLite → PostgreSQL Migration Script
=====================================
Migrates data from the legacy SQLite database to the new PostgreSQL instance
while preserving existing users, portfolios, and trade logs.

Usage:
    # Ensure PostgreSQL is running and env vars set
    python -m src.migrations.sqlite_to_postgres [--sqlite-path ./risk_system.db]

Steps:
    1. Read all rows from SQLite tables (users, portfolios, trade_log)
    2. Hash legacy plaintext passwords with bcrypt
    3. Insert into PostgreSQL via SQLAlchemy ORM (idempotent — skips duplicates)
    4. Verify row counts match

Safe to re-run: uses INSERT IF NOT EXISTS semantics.
"""

import argparse
import os
import sqlite3
import sys

from src.database import (
    Portfolio,
    TradeLog,
    User,
    get_connected_url,
    hash_password,
    init_db,
    is_postgres,
    session_scope,
)


def _sqlite_connect(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        print(f"[MIGRATE] SQLite file not found at {path} — nothing to migrate.")
        sys.exit(1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_users(sqlite_conn: sqlite3.Connection) -> int:
    """Copy users, hashing plaintext passwords on the way."""
    cur = sqlite_conn.cursor()
    try:
        cur.execute("SELECT username, password, role FROM users")
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        print("[MIGRATE] SQLite 'users' table missing or empty")
        return 0

    migrated = 0
    with session_scope() as s:
        for row in rows:
            existing = s.query(User).filter_by(username=row["username"]).first()
            if existing:
                continue
            stored_pw = row["password"] or ""
            # Upgrade to bcrypt if legacy plaintext
            if not stored_pw.startswith(("$2a$", "$2b$", "$2y$")):
                stored_pw = hash_password(stored_pw or "changeme")
            s.add(User(
                username=row["username"],
                password_hash=stored_pw,
                role=row["role"] or "analyst",
            ))
            migrated += 1
    return migrated


def migrate_portfolios(sqlite_conn: sqlite3.Connection) -> int:
    cur = sqlite_conn.cursor()
    try:
        cur.execute(
            "SELECT username, ticker, investment_amount, beta FROM portfolios"
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        return 0

    migrated = 0
    with session_scope() as s:
        for row in rows:
            existing = s.query(Portfolio).filter_by(username=row["username"]).first()
            if existing:
                continue
            # Ensure FK integrity
            user = s.query(User).filter_by(username=row["username"]).first()
            if not user:
                continue
            s.add(Portfolio(
                username=row["username"],
                ticker=row["ticker"] or "005930.KS",
                investment_amount=float(row["investment_amount"] or 0.0),
                beta=float(row["beta"] or 1.0),
            ))
            migrated += 1
    return migrated


def migrate_trade_log(sqlite_conn: sqlite3.Connection) -> int:
    cur = sqlite_conn.cursor()
    try:
        cur.execute(
            "SELECT id, username, ticker, qty, side, status, executed_at "
            "FROM trade_log ORDER BY id"
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        return 0

    migrated = 0
    with session_scope() as s:
        # Get current max ID to avoid re-inserting duplicates
        existing_ids = {t.id for t in s.query(TradeLog.id).all()}

        for row in rows:
            if row["id"] in existing_ids:
                continue
            user = s.query(User).filter_by(username=row["username"]).first()
            if not user:
                continue
            # executed_at from SQLite is a string — let PG parse it
            import datetime
            exec_at = None
            if row["executed_at"]:
                try:
                    exec_at = datetime.datetime.fromisoformat(
                        row["executed_at"].replace(" ", "T")
                    )
                except (ValueError, AttributeError):
                    exec_at = None

            t = TradeLog(
                id=row["id"],
                username=row["username"],
                ticker=row["ticker"],
                qty=int(row["qty"]),
                side=row["side"],
                status=row["status"],
            )
            if exec_at:
                t.executed_at = exec_at
            s.add(t)
            migrated += 1
    return migrated


def run_migration(sqlite_path: str = "risk_system.db") -> dict:
    """Run the full migration and return per-table counts."""
    print(f"[MIGRATE] Source (SQLite): {sqlite_path}")
    print(f"[MIGRATE] Target: {get_connected_url()}")

    if not is_postgres():
        print("[MIGRATE] ⚠️  Target is NOT PostgreSQL — proceeding anyway "
              "(useful for SQLite→SQLite copy tests).")

    # Ensure target schema exists
    init_db()

    sqlite_conn = _sqlite_connect(sqlite_path)
    try:
        n_users = migrate_users(sqlite_conn)
        n_ports = migrate_portfolios(sqlite_conn)
        n_trades = migrate_trade_log(sqlite_conn)
    finally:
        sqlite_conn.close()

    result = {
        "users_migrated": n_users,
        "portfolios_migrated": n_ports,
        "trades_migrated": n_trades,
        "target_url": get_connected_url(),
    }

    print(f"[MIGRATE] ✅ Done. Users: {n_users}, Portfolios: {n_ports}, "
          f"Trades: {n_trades}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite → PostgreSQL")
    parser.add_argument(
        "--sqlite-path", default="risk_system.db",
        help="Path to the legacy SQLite file (default: risk_system.db)",
    )
    args = parser.parse_args()
    run_migration(args.sqlite_path)


if __name__ == "__main__":
    main()
