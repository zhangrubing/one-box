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
                    # latest ts across cpu_data as anchor
                    async with db.execute("SELECT ts,cpu_percent FROM cpu_data ORDER BY ts DESC LIMIT 1") as cur:
                        crow = await cur.fetchone()
                    if crow:
                        ts = int(crow[0])
                        if ts != last_ts:
                            last_ts = ts
                            # fetch other components at same ts (best-effort)
                            async with db.execute("SELECT load1,load5,load15 FROM load_data WHERE ts=?", (ts,)) as c2:
                                lrow = await c2.fetchone()
                            # 内存数据优先取同一 ts；若缺失，回退到 <= ts 的最近一条，避免前端出现 NaN
                            async with db.execute("SELECT mem_used,mem_total,mem_percent FROM mem_data WHERE ts=?", (ts,)) as c3:
                                mrow = await c3.fetchone()
                            if not mrow:
                                async with db.execute("SELECT mem_used,mem_total,mem_percent FROM mem_data WHERE ts<=? ORDER BY ts DESC LIMIT 1", (ts,)) as c3b:
                                    mrow = await c3b.fetchone()
                            async with db.execute("SELECT processes FROM proc_data WHERE ts=?", (ts,)) as c4:
                                prow = await c4.fetchone()
                            async with db.execute("SELECT disk_mb_s FROM diskio_data WHERE ts=?", (ts,)) as c5:
                                drow = await c5.fetchone()
                            async with db.execute("SELECT gpu_util_avg,gpu_temp_avg FROM gpu_data WHERE ts=?", (ts,)) as c6:
                                grow = await c6.fetchone()
                            snap = {
                                "time": ts,
                                "cpu_percent": crow[1],
                                "load_avg": (lrow[0], lrow[1], lrow[2]) if lrow else (None, None, None),
                                "mem": {"used": mrow[0] if mrow else 0, "total": mrow[1] if mrow else 0},
                                "processes": (prow[0] if prow else None),
                                "mem_percent": (mrow[2] if mrow and mrow[2] is not None else ( (mrow[0]/mrow[1]*100.0) if mrow and mrow[1] else 0.0 )),
                                "disk_mb_s": (drow[0] if drow else None),
                                "gpu_util_avg": (grow[0] if grow else None),
                                "gpu_temp_avg": (grow[1] if grow else None),
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
    date: str | None = None,
    fields: str | None = None,
    user: dict = Depends(require_user)
):
    """Return historical system metrics from metric_samples between [start, end].
    times are Unix seconds. fields is comma-separated subset of columns.
    """
    cols_all = ["ts","cpu_percent","load1","load5","load15","mem_used","mem_total","processes","mem_percent","disk_mb_s","gpu_util_avg","gpu_temp_avg"]
    cols = [c for c in (fields.split(",") if fields else cols_all) if c in cols_all]
    if "ts" not in cols:
        cols = ["ts"] + cols
    now = int(time.time())
    if date:
        # If date is provided (YYYY-MM-DD), constrain by date directly using index
        date = str(date)
        range_clause = "date = ?"
        range_args = (date,)
    else:
        if end is None:
            end = now
        if start is None:
            start = end - 3600  # default 1 hour
        range_clause = "ts BETWEEN ? AND ?"
        range_args = (int(start), int(end))
    # Compose from split tables by ts (best-effort join)
    items = []
    async with aiosqlite.connect(DB_PATH) as db:
        # anchor by ts from cpu_data in range/date
        async with db.execute(f"SELECT ts,cpu_percent FROM cpu_data WHERE {range_clause} ORDER BY ts ASC", range_args) as cur:
            async for crow in cur:
                ts, cpu = int(crow[0]), crow[1]
                row = {"ts": ts, "cpu_percent": cpu}
                # fetch per table
                async with db.execute("SELECT load1,load5,load15 FROM load_data WHERE ts=?", (ts,)) as c2:
                    l = await c2.fetchone()
                if l: row.update({"load1": l[0], "load5": l[1], "load15": l[2]})
                # 内存数据缺失时向后回看，避免 NaN
                async with db.execute("SELECT mem_used,mem_total,mem_percent FROM mem_data WHERE ts=?", (ts,)) as c3:
                    m = await c3.fetchone()
                if not m:
                    async with db.execute("SELECT mem_used,mem_total,mem_percent FROM mem_data WHERE ts<=? ORDER BY ts DESC LIMIT 1", (ts,)) as c3b:
                        m = await c3b.fetchone()
                if m:
                    mem_used, mem_total, mem_pct = m[0], m[1], m[2]
                    if mem_pct is None:
                        mem_pct = (float(mem_used)/mem_total*100.0) if mem_total else 0.0
                    row.update({"mem_used": mem_used, "mem_total": mem_total, "mem_percent": mem_pct})
                async with db.execute("SELECT processes FROM proc_data WHERE ts=?", (ts,)) as c4:
                    p = await c4.fetchone()
                if p: row.update({"processes": p[0]})
                async with db.execute("SELECT disk_mb_s FROM diskio_data WHERE ts=?", (ts,)) as c5:
                    d = await c5.fetchone()
                if d: row.update({"disk_mb_s": d[0]})
                async with db.execute("SELECT gpu_util_avg,gpu_temp_avg FROM gpu_data WHERE ts=?", (ts,)) as c6:
                    g = await c6.fetchone()
                if g: row.update({"gpu_util_avg": g[0], "gpu_temp_avg": g[1]})
                # filter to requested fields
                out = {k: v for k, v in row.items() if k in cols}
                items.append(out)
    return {"items": items, "fields": cols}


@router.get("/api/metrics/network")
async def api_metrics_network(
    request: Request,
    iface: str = "__total__",
    start: int | None = None,
    end: int | None = None,
    date: str | None = None,
    fields: str | None = None,
    user: dict = Depends(require_user)
):
    cols_all = ["ts","iface","rx_bytes","tx_bytes","errin","errout","rx_kbps","tx_kbps","latency_ms"]
    cols = [c for c in (fields.split(",") if fields else cols_all) if c in cols_all]
    if "ts" not in cols:
        cols = ["ts"] + cols
    now = int(time.time())
    if date:
        placeholders = ", ".join(cols)
        sql = f"SELECT {placeholders} FROM net_data WHERE iface = ? AND date = ? ORDER BY ts ASC"
        args = (iface, date)
    else:
        if end is None:
            end = now
        if start is None:
            start = end - 3600
        placeholders = ", ".join(cols)
        sql = f"SELECT {placeholders} FROM net_data WHERE iface = ? AND ts BETWEEN ? AND ? ORDER BY ts ASC"
        args = (iface, int(start), int(end))
    items = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sql, args) as cur:
            async for row in cur:
                obj = {cols[i]: row[i] for i in range(len(cols))}
                items.append(obj)
    return {"items": items, "fields": cols, "iface": iface}
