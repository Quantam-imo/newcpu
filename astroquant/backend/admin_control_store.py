import json
import sqlite3
import threading
import time
from pathlib import Path


class AdminControlStore:
    def __init__(self, db_path: str | Path = "data/admin_control.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        with self.lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    role TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    auto_trading_enabled INTEGER NOT NULL DEFAULT 1,
                    risk_multiplier REAL NOT NULL DEFAULT 1.0,
                    banned INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS prop_rules (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    profit_target_pct REAL NOT NULL,
                    daily_dd_pct REAL NOT NULL,
                    overall_dd_pct REAL NOT NULL,
                    lock_level REAL NOT NULL,
                    min_profitable_days INTEGER NOT NULL,
                    leverage_limit REAL NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS engine_controls (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    ict_enabled INTEGER NOT NULL,
                    iceberg_enabled INTEGER NOT NULL,
                    gann_enabled INTEGER NOT NULL,
                    astro_enabled INTEGER NOT NULL,
                    confluence_threshold REAL NOT NULL,
                    confidence_threshold REAL NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_controls (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    spread_max_limit REAL NOT NULL,
                    slippage_tolerance REAL NOT NULL,
                    cooldown_seconds INTEGER NOT NULL,
                    max_trades_per_day INTEGER NOT NULL,
                    max_concurrent_trades INTEGER NOT NULL,
                    execution_timeout_seconds INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_limits (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    max_lot_size REAL NOT NULL,
                    max_risk_per_trade REAL NOT NULL,
                    daily_max_trades INTEGER NOT NULL,
                    risk_multiplier_phase1 REAL NOT NULL,
                    risk_multiplier_phase2 REAL NOT NULL,
                    risk_multiplier_funded REAL NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_activation (
                    symbol TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload_json TEXT,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()
            conn.close()
            self._ensure_defaults()

    def _ensure_defaults(self):
        now = int(time.time())
        conn = self._connect()
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM prop_rules WHERE id = 1")
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO prop_rules (id, profit_target_pct, daily_dd_pct, overall_dd_pct, lock_level, min_profitable_days, leverage_limit, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (8.0, 1.5, 8.0, 52000.0, 3, 20.0, now),
            )

        cur.execute("SELECT 1 FROM engine_controls WHERE id = 1")
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO engine_controls (id, ict_enabled, iceberg_enabled, gann_enabled, astro_enabled, confluence_threshold, confidence_threshold, updated_at)
                VALUES (1, 1, 1, 1, 1, ?, ?, ?)
                """,
                (0.5, 55.0, now),
            )
        else:
            # Backward-compatible migration for existing DBs created before GANN toggle support.
            cur.execute("PRAGMA table_info(engine_controls)")
            cols = {str(row[1]).lower() for row in (cur.fetchall() or [])}
            if "gann_enabled" not in cols:
                cur.execute("ALTER TABLE engine_controls ADD COLUMN gann_enabled INTEGER NOT NULL DEFAULT 1")
                cur.execute("UPDATE engine_controls SET gann_enabled = 1 WHERE gann_enabled IS NULL")

        cur.execute("SELECT 1 FROM execution_controls WHERE id = 1")
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO execution_controls (id, spread_max_limit, slippage_tolerance, cooldown_seconds, max_trades_per_day, max_concurrent_trades, execution_timeout_seconds, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (2.5, 0.5, 300, 20, 2, 10, now),
            )

        cur.execute("SELECT 1 FROM risk_limits WHERE id = 1")
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO risk_limits (id, max_lot_size, max_risk_per_trade, daily_max_trades, risk_multiplier_phase1, risk_multiplier_phase2, risk_multiplier_funded, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (10.0, 1.0, 20, 1.0, 1.0, 1.0, now),
            )

        conn.commit()
        conn.close()

    @staticmethod
    def _row_to_dict(cursor, row):
        return {desc[0]: row[idx] for idx, desc in enumerate(cursor.description)}

    def _fetch_single(self, table_name: str):
        conn = self._connect()
        conn.row_factory = self._row_to_dict
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM {table_name} WHERE id = 1")
        row = cur.fetchone() or {}
        conn.close()
        return row

    def get_prop_rules(self):
        return self._fetch_single("prop_rules")

    def get_engine_controls(self):
        return self._fetch_single("engine_controls")

    def get_execution_controls(self):
        return self._fetch_single("execution_controls")

    def get_risk_limits(self):
        return self._fetch_single("risk_limits")

    def upsert_singleton(self, table_name: str, data: dict):
        payload = dict(data or {})
        payload["id"] = 1
        payload["updated_at"] = int(time.time())
        columns = sorted(payload.keys())
        values = [payload[col] for col in columns]
        placeholders = ",".join(["?"] * len(columns))
        updates = ",".join([f"{col}=excluded.{col}" for col in columns if col != "id"])

        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}",
            values,
        )
        conn.commit()
        conn.close()

    def list_users(self):
        conn = self._connect()
        conn.row_factory = self._row_to_dict
        cur = conn.cursor()
        cur.execute("SELECT * FROM users ORDER BY username")
        rows = cur.fetchall() or []
        conn.close()
        return rows

    def upsert_user(self, username: str, role: str, phase: str, auto_trading_enabled: bool, risk_multiplier: float, banned: bool):
        now = int(time.time())
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (username, role, phase, auto_trading_enabled, risk_multiplier, banned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                role=excluded.role,
                phase=excluded.phase,
                auto_trading_enabled=excluded.auto_trading_enabled,
                risk_multiplier=excluded.risk_multiplier,
                banned=excluded.banned,
                updated_at=excluded.updated_at
            """,
            (
                str(username).strip(),
                str(role).upper(),
                str(phase).upper(),
                int(bool(auto_trading_enabled)),
                float(risk_multiplier),
                int(bool(banned)),
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()

    def set_user_ban(self, username: str, banned: bool):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET banned = ?, updated_at = ? WHERE username = ?",
            (int(bool(banned)), int(time.time()), str(username).strip()),
        )
        conn.commit()
        updated = cur.rowcount
        conn.close()
        return updated > 0

    def get_symbols(self):
        conn = self._connect()
        conn.row_factory = self._row_to_dict
        cur = conn.cursor()
        cur.execute("SELECT symbol, enabled, updated_at FROM symbol_activation ORDER BY symbol")
        rows = cur.fetchall() or []
        conn.close()
        return rows

    def set_symbol(self, symbol: str, enabled: bool):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO symbol_activation (symbol, enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at
            """,
            (str(symbol).upper().strip(), int(bool(enabled)), int(time.time())),
        )
        conn.commit()
        conn.close()

    def list_audit(self, limit: int = 200, category: str | None = None):
        conn = self._connect()
        conn.row_factory = self._row_to_dict
        cur = conn.cursor()
        if category:
            cur.execute(
                "SELECT * FROM audit_log WHERE category = ? ORDER BY id DESC LIMIT ?",
                (str(category).upper(), max(1, min(int(limit), 1000))),
            )
        else:
            cur.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            )
        rows = cur.fetchall() or []
        conn.close()

        for row in rows:
            payload = row.get("payload_json")
            if payload:
                try:
                    row["payload"] = json.loads(payload)
                except Exception:
                    row["payload"] = payload
            else:
                row["payload"] = None
        return rows

    def audit(self, category: str, action: str, actor: str, payload: dict | None = None):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_log (category, action, actor, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                str(category or "SYSTEM").upper(),
                str(action or "UNKNOWN").upper(),
                str(actor or "system"),
                json.dumps(payload or {}, ensure_ascii=False),
                int(time.time()),
            ),
        )
        conn.commit()
        conn.close()
