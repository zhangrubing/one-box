import asyncio, os, time
import aiosqlite
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, DB_PATH
from .db import init_db
from .middleware import AuthMiddleware
from .routers import auth as r_auth
from .routers import users as r_users
from .routers import users_page as r_users_page
from .routers import dashboard as r_dashboard
from .routers import reports as r_reports
from .routers import hardware as r_hardware
from .routers import gpu as r_gpu
from .routers import network as r_network
from .routers import storage as r_storage
from .routers import logs as r_logs
from .routers import alerts as r_alerts
from .routers import operations as r_ops
from .routers import audit as r_audit
from .routers import about as r_about
from .utils.system import collect_system_snapshot
from .utils.system import collect_network_rates


app = FastAPI(title="一体机监控系统")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
async def on_startup():
    await init_db()
    asyncio.create_task(_sampler())
    asyncio.create_task(_retention_worker())


@app.get("/ping")
async def ping():
    return {"ok": True}


async def _sampler():
    interval = int(os.environ.get("SAMPLE_INTERVAL", "5"))
    while True:
        try:
            snap = collect_system_snapshot()
            async with aiosqlite.connect(DB_PATH) as db:
                ts = int(time.time())
                await db.execute("INSERT INTO cpu_data(ts,cpu_percent) VALUES(?,?)", (ts, snap["cpu_percent"]))
                await db.execute("INSERT INTO load_data(ts,load1,load5,load15) VALUES(?,?,?,?)", (ts, snap["load_avg"][0], snap["load_avg"][1], snap["load_avg"][2]))
                await db.execute("INSERT INTO mem_data(ts,mem_used,mem_total,mem_percent) VALUES(?,?,?,?)", (ts, int(snap["mem"]["used"]), int(snap["mem"]["total"]), float(snap.get("mem_percent") or 0.0)))
                await db.execute("INSERT INTO proc_data(ts,processes) VALUES(?,?)", (ts, snap["processes"]))
                await db.execute("INSERT INTO diskio_data(ts,disk_mb_s) VALUES(?,?)", (ts, float(snap.get("disk_mb_s") or 0.0)))
                await db.execute("INSERT INTO gpu_data(ts,gpu_util_avg,gpu_temp_avg) VALUES(?,?,?)", (ts, float(snap.get("gpu_util_avg") or 0.0), float(snap.get("gpu_temp_avg") or 0.0)))
                await db.commit()
            # network per-nic sampling
            try:
                net = collect_network_rates()
                ts = int(time.time())
                async with aiosqlite.connect(DB_PATH) as db:
                    for name, item in (net.get("ifaces") or {}).items():
                        await db.execute(
                            "INSERT INTO net_data(ts,iface,rx_bytes,tx_bytes,errin,errout,rx_kbps,tx_kbps,latency_ms) VALUES(?,?,?,?,?,?,?,?,?)",
                            (
                                ts, name,
                                int(item.get("rx_bytes") or 0), int(item.get("tx_bytes") or 0),
                                int(item.get("errin") or 0), int(item.get("errout") or 0),
                                float(item.get("rx_kbps") or 0.0), float(item.get("tx_kbps") or 0.0),
                                None,
                            ),
                        )
                    # total row with latency
                    tot = net.get("total") or {}
                    await db.execute(
                        "INSERT INTO net_data(ts,iface,rx_bytes,tx_bytes,errin,errout,rx_kbps,tx_kbps,latency_ms) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            ts, "__total__",
                            None, None,
                            int(tot.get("errin") or 0), int(tot.get("errout") or 0),
                            float(tot.get("rx_kbps") or 0.0), float(tot.get("tx_kbps") or 0.0),
                            (net.get("latency_ms") if isinstance(net.get("latency_ms"), (int,float)) else None),
                        ),
                    )
                    await db.commit()
            except Exception:
                pass
        except Exception:
            pass
        await asyncio.sleep(interval)


async def _retention_worker():
    """Periodic deletion of samples older than RETENTION_DAYS (default 14)."""
    days = int(os.environ.get("RETENTION_DAYS", "14"))
    batch = int(os.environ.get("RETENTION_DELETE_BATCH", "50000"))
    # run hourly
    while True:
        try:
            now = int(time.time())
            cutoff = now - days * 86400
            async with aiosqlite.connect(DB_PATH) as db:
                # delete in batches to avoid long locks
                for table in ("cpu_data","mem_data","load_data","proc_data","diskio_data","gpu_data","net_data","metric_samples"):
                    await db.execute(
                        f"DELETE FROM {table} WHERE ts < ? LIMIT ?",
                        (cutoff, batch)
                    )
                await db.commit()
        except Exception:
            pass
        await asyncio.sleep(3600)


# middleware and routers
app.add_middleware(AuthMiddleware)
app.include_router(r_auth.router)
app.include_router(r_users.router)
app.include_router(r_users_page.router)
app.include_router(r_dashboard.router)
app.include_router(r_reports.router)
app.include_router(r_hardware.router)
app.include_router(r_gpu.router)
app.include_router(r_network.router)
app.include_router(r_storage.router)
app.include_router(r_logs.router)
app.include_router(r_alerts.router)
app.include_router(r_ops.router)
app.include_router(r_audit.router)
app.include_router(r_about.router)
