import asyncio
from fastapi import APIRouter, Depends, Request
import aiosqlite, os, time
from ..config import DB_PATH
from fastapi.responses import HTMLResponse, StreamingResponse
from ..deps import require_user
from ..utils.system import collect_system_snapshot
from ..web import render


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root_redirect(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return render(request, "dashboard.html")


@router.get("/api/process/top")
async def api_process_top(duration: int = 30, limit: int = 10, user: dict = Depends(require_user)):
    import psutil
    procs = {}
    for p in psutil.process_iter(attrs=["pid","name","username"]):
        try:
            p.cpu_percent(interval=None)
            procs[p.pid] = {"pid": p.pid, "name": p.info.get("name"), "user": p.info.get("username"), "cpu": 0.0, "mem_rss": p.memory_info().rss}
        except Exception:
            pass
    await asyncio.sleep(max(1, int(duration)))
    out = []
    for p in psutil.process_iter(attrs=["pid","name","username"]):
        if p.pid not in procs:
            continue
        try:
            c = p.cpu_percent(interval=None)
            procs[p.pid]["cpu"] = c
            procs[p.pid]["mem_rss"] = p.memory_info().rss
            out.append(procs[p.pid])
        except Exception:
            pass
    out.sort(key=lambda x: x.get("cpu", 0), reverse=True)
    return {"items": out[:limit]}


async def sse_event(data: dict, event: str | None = None) -> bytes:
    buf = ""
    if event:
        buf += f"event: {event}\n"
    import json as _json
    payload = _json.dumps(data, ensure_ascii=False)
    for line in payload.splitlines():
        buf += f"data: {line}\n"
    buf += "\n"
    return buf.encode("utf-8")


@router.get("/sse/metrics")
async def sse_metrics(request: Request, user: dict = Depends(require_user)):
    """Stream latest metrics sampled and stored in DB to keep UI consistent with stored data."""
    async def event_gen():
        last_ts = 0
        while True:
            if await request.is_disconnected():
                break
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    # read latest metric_samples row
                    async with db.execute(
                        "SELECT ts,cpu_percent,load1,load5,load15,mem_used,mem_total,processes,mem_percent,disk_mb_s,gpu_util_avg,gpu_temp_avg"
                        " FROM metric_samples ORDER BY ts DESC LIMIT 1"
                    ) as cur:
                        row = await cur.fetchone()
                    if row:
                        ts = int(row[0])
                        if ts != last_ts:
                            last_ts = ts
                            snap = {
                                "time": ts,
                                "cpu_percent": row[1],
                                "load_avg": (row[2], row[3], row[4]),
                                "mem": {"used": row[5], "total": row[6]},
                                "processes": row[7],
                                "mem_percent": row[8],
                                "disk_mb_s": row[9],
                                "gpu_util_avg": row[10],
                                "gpu_temp_avg": row[11],
                            }
                            yield await sse_event(snap, event="metrics")
            except Exception:
                pass
            await asyncio.sleep(1.0)
    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/api/metrics/system")
async def api_metrics_system(
    request: Request,
    start: int | None = None,
    end: int | None = None,
    fields: str | None = None,
    user: dict = Depends(require_user)
):
    """Return historical system metrics from metric_samples between [start, end].
    times are Unix seconds. fields is comma-separated subset of columns.
    """
    cols_all = [
        "ts","cpu_percent","load1","load5","load15","mem_used","mem_total","processes","mem_percent","disk_mb_s","gpu_util_avg","gpu_temp_avg"
    ]
    cols = [c for c in (fields.split(",") if fields else cols_all) if c in cols_all]
    if "ts" not in cols:
        cols = ["ts"] + cols
    now = int(time.time())
    if end is None:
        end = now
    if start is None:
        start = end - 3600  # default 1 hour
    sql = f"SELECT {', '.join(cols)} FROM metric_samples WHERE ts BETWEEN ? AND ? ORDER BY ts ASC"
    items = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sql, (int(start), int(end))) as cur:
            async for row in cur:
                obj = {cols[i]: row[i] for i in range(len(cols))}
                items.append(obj)
    return {"items": items, "fields": cols}


@router.get("/api/metrics/network")
async def api_metrics_network(
    request: Request,
    iface: str = "__total__",
    start: int | None = None,
    end: int | None = None,
    fields: str | None = None,
    user: dict = Depends(require_user)
):
    cols_all = ["ts","iface","rx_bytes","tx_bytes","errin","errout","rx_kbps","tx_kbps","latency_ms"]
    cols = [c for c in (fields.split(",") if fields else cols_all) if c in cols_all]
    if "ts" not in cols:
        cols = ["ts"] + cols
    now = int(time.time())
    if end is None:
        end = now
    if start is None:
        start = end - 3600
    placeholders = ", ".join(cols)
    sql = f"SELECT {placeholders} FROM net_samples WHERE iface = ? AND ts BETWEEN ? AND ? ORDER BY ts ASC"
    items = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sql, (iface, int(start), int(end))) as cur:
            async for row in cur:
                obj = {cols[i]: row[i] for i in range(len(cols))}
                items.append(obj)
    return {"items": items, "fields": cols, "iface": iface}
