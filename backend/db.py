import os
import sqlite3
from pathlib import Path
import aiosqlite
from .config import DB_PATH
from .crypto import hash_password


SCHEMA_SQL = '''
PRAGMA journal_mode=DELETE;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  token_version INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT,
  action TEXT,
  detail TEXT,
  ip TEXT,
  ua TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  acknowledged INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sys_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- system metrics split into dedicated tables
CREATE TABLE IF NOT EXISTS cpu_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  date TEXT GENERATED ALWAYS AS (strftime('%Y-%m-%d', ts, 'unixepoch')) VIRTUAL,
  cpu_percent REAL
  , created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mem_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  date TEXT GENERATED ALWAYS AS (strftime('%Y-%m-%d', ts, 'unixepoch')) VIRTUAL,
  mem_used INTEGER,
  mem_total INTEGER,
  mem_percent REAL
  , created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS load_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  date TEXT GENERATED ALWAYS AS (strftime('%Y-%m-%d', ts, 'unixepoch')) VIRTUAL,
  load1 REAL,
  load5 REAL,
  load15 REAL
  , created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS proc_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  date TEXT GENERATED ALWAYS AS (strftime('%Y-%m-%d', ts, 'unixepoch')) VIRTUAL,
  processes INTEGER
  , created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS diskio_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  date TEXT GENERATED ALWAYS AS (strftime('%Y-%m-%d', ts, 'unixepoch')) VIRTUAL,
  disk_mb_s REAL
  , created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS gpu_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  date TEXT GENERATED ALWAYS AS (strftime('%Y-%m-%d', ts, 'unixepoch')) VIRTUAL,
  gpu_util_avg REAL,
  gpu_temp_avg REAL
  , created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS net_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  date TEXT GENERATED ALWAYS AS (strftime('%Y-%m-%d', ts, 'unixepoch')) VIRTUAL,
  iface TEXT NOT NULL,
  rx_bytes INTEGER,
  tx_bytes INTEGER,
  errin INTEGER,
  errout INTEGER,
  rx_kbps REAL,
  tx_kbps REAL,
  latency_ms REAL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
'''


async def ensure_column(db, table: str, col: str, decl: str):
    try:
        cur = await db.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in await cur.fetchall()]
        if col not in cols:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    except Exception:
        # ignore if busy / column exists
        pass


async def init_db():
    # Ensure DB directory exists (e.g., BASE_DIR/data)
    try:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # As a fallback, try os.makedirs
        try:
            os.makedirs(Path(DB_PATH).parent, exist_ok=True)
        except Exception:
            pass
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        # indexes for time-range queries
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_cpu_data_ts ON cpu_data(ts)")
        except Exception:
            pass
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_net_data_iface_ts ON net_data(iface, ts)")
        except Exception:
            pass
        # date indexes for quick daily filtering
        for t in ("cpu_data","mem_data","load_data","proc_data","diskio_data","gpu_data","net_data"):
            try:
                await db.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_date ON {t}(date)")
            except Exception:
                pass
        # additional indexes per table
        for t in ("mem_data","load_data","proc_data","diskio_data","gpu_data"):
            try:
                await db.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_ts ON {t}(ts)")
            except Exception:
                pass
        # keep backward-compat columns if old table exists
        try:
            await ensure_column(db, "metric_samples", "mem_percent", "REAL")
            await ensure_column(db, "metric_samples", "disk_mb_s", "REAL")
            await ensure_column(db, "metric_samples", "gpu_util_avg", "REAL")
            await ensure_column(db, "metric_samples", "gpu_temp_avg", "REAL")
        except Exception:
            pass
        # bootstrap admin user
        async with db.execute("SELECT COUNT(1) FROM users") as cur:
            row = await cur.fetchone()
            cnt = row[0] if row else 0
        if cnt == 0:
            await db.execute(
                "INSERT INTO users(username,password_hash,is_admin) VALUES(?,?,1)",
                ("admin", hash_password("admin123"))
            )
        await db.commit()
