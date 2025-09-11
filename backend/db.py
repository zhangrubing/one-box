import sqlite3
import aiosqlite
from .config import DB_PATH
from .crypto import hash_password


SCHEMA_SQL = '''
PRAGMA journal_mode=WAL;
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
CREATE TABLE IF NOT EXISTS metric_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  cpu_percent REAL,
  load1 REAL,
  load5 REAL,
  load15 REAL,
  mem_used INTEGER,
  mem_total INTEGER,
  processes INTEGER
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        # new columns for metrics
        await ensure_column(db, "metric_samples", "mem_percent", "REAL")
        await ensure_column(db, "metric_samples", "disk_mb_s", "REAL")
        await ensure_column(db, "metric_samples", "gpu_util_avg", "REAL")
        await ensure_column(db, "metric_samples", "gpu_temp_avg", "REAL")
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

