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

            # Threshold-based alerts with 10-minute rate limiting per alert title
            try:
                CPU_HIGH = float(os.environ.get("ALERT_CPU_PCT", "90"))
                MEM_HIGH = float(os.environ.get("ALERT_MEM_PCT", "90"))
                GPU_TEMP_HIGH = float(os.environ.get("ALERT_GPU_TEMP", "85"))
                DISK_MB_S_HIGH = float(os.environ.get("ALERT_DISK_MB_S", "1000"))

                async def maybe_alert(title: str, message: str, level: str = "WARN", min_interval_sec: int = 600):
                    # Only insert if there is no same-title alert in the last min_interval_sec
                    async with aiosqlite.connect(DB_PATH) as db2:
                        sql = f"SELECT id FROM alerts WHERE title=? AND created_at >= datetime('now','-{min_interval_sec} seconds') LIMIT 1"
                        cur = await db2.execute(sql, (title,))
                        row = await cur.fetchone()
                        if not row:
                            await db2.execute("INSERT INTO alerts (level, title, message) VALUES (?,?,?)", (level, title, message))
                            await db2.commit()

                # CPU
                cpuv = float(snap.get("cpu_percent") or 0)
                if cpuv >= CPU_HIGH:
                    await maybe_alert(
                        title="CPU 使用率过高",
                        message=f"当前 {cpuv:.1f}% ≥ 阈值 {CPU_HIGH:.1f}%",
                        level="WARN",
                    )
                # Memory
                memv = float(snap.get("mem_percent") or 0)
                if memv >= MEM_HIGH:
                    total_gb = (snap.get("mem") or {}).get("total") or 0
                    used_gb = (snap.get("mem") or {}).get("used") or 0
                    try:
                        total_gb = total_gb/1073741824
                        used_gb = used_gb/1073741824
                    except Exception:
                        pass
                    await maybe_alert(
                        title="内存占用过高",
                        message=f"当前 {memv:.1f}% (≈ {used_gb:.0f}/{total_gb:.0f} GB) ≥ 阈值 {MEM_HIGH:.1f}%",
                        level="WARN",
                    )
                # Disk IO
                dsk = float(snap.get("disk_mb_s") or 0)
                if dsk >= DISK_MB_S_HIGH:
                    await maybe_alert(
                        title="磁盘 IO 过高",
                        message=f"当前 {dsk:.1f} MB/s ≥ 阈值 {DISK_MB_S_HIGH:.1f} MB/s",
                        level="WARN",
                    )
                # GPU temperature
                gt = float(snap.get("gpu_temp_avg") or 0)
                if gt >= GPU_TEMP_HIGH:
                    await maybe_alert(
                        title="GPU 温度过高",
                        message=f"当前 {gt:.0f}℃ ≥ 阈值 {GPU_TEMP_HIGH:.0f}℃",
                        level="ERROR",
                    )
            except Exception:
                # Alerting must not break sampling
                pass
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
                # Network-related alert: high latency on total
                try:
                    LAT_HIGH = float(os.environ.get("ALERT_LAT_MS", "300"))
                    lt = net.get("latency_ms")
                    if isinstance(lt, (int, float)) and lt >= LAT_HIGH:
                        async with aiosqlite.connect(DB_PATH) as adb:
                            sql = "SELECT id FROM alerts WHERE title=? AND created_at >= datetime('now','-600 seconds') LIMIT 1"
                            ttl = "网络延迟过高"
                            row = await (await adb.execute(sql, (ttl,))).fetchone()
                            if not row:
                                msg = f"当前延迟 {lt:.0f} ms ≥ 阈值 {LAT_HIGH:.0f} ms"
                                await adb.execute("INSERT INTO alerts(level,title,message) VALUES(?,?,?)", ("WARN", ttl, msg))
                                await adb.commit()
                except Exception:
                    pass
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
