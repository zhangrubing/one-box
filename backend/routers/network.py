import time, math, sqlite3, asyncio
from typing import Optional, Dict
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import aiosqlite, psutil
from ..deps import require_user
from ..config import DB_PATH
from ..web import render
from ..utils.system import detect_primary_interface


router = APIRouter()


@router.get("/network", response_class=HTMLResponse)
async def network_page(request: Request):
    return render(request, "network.html")


@router.get("/api/system/network")
async def api_system_network(request: Request, user: dict = Depends(require_user)):
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    out = {}
    for name, st in stats.items():
        o = {"isup": st.isup, "duplex": getattr(st, "duplex", None), "speed": getattr(st, "speed", None), "mtu": st.mtu, "addrs": []}
        for a in addrs.get(name, []):
            o["addrs"].append({"family": str(a.family).split(".")[-1], "address": a.address, "netmask": a.netmask, "broadcast": a.broadcast, "ptp": a.ptp})
        out[name] = o
    return out


@router.get("/api/network/meta")
async def api_network_meta(user: dict = Depends(require_user)):
    # Gather interface info similar to /api/system/network
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    out: Dict[str, Dict] = {}
    for name, st in stats.items():
        o = {"isup": st.isup, "duplex": getattr(st, "duplex", None), "speed": getattr(st, "speed", None), "mtu": st.mtu, "addrs": []}
        for a in addrs.get(name, []):
            o["addrs"].append({"family": str(a.family).split(".")[-1], "address": a.address, "netmask": a.netmask, "broadcast": a.broadcast, "ptp": a.ptp})
        out[name] = o
    primary = detect_primary_interface()
    up_ifaces = [k for k,v in out.items() if v.get("isup")]
    return {"primary_iface": primary, "ifaces": out, "up_ifaces": up_ifaces}


@router.get("/api/network/speeds")
async def api_network_speeds(iface: str = "__total__", minutes: int = 60, user: dict = Depends(require_user)):
    since = int(time.time()) - max(1, minutes) * 60
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = await (await db.execute(
            "SELECT ts, rx_kbps, tx_kbps, latency_ms FROM net_samples WHERE iface=? AND ts>=? ORDER BY ts",
            (iface, since),
        )).fetchall()
    items = [dict(r) for r in rows]
    if len(items) > 720:
        step = math.ceil(len(items)/720)
        items = items[::step]
    rx_avg = sum((x.get("rx_kbps") or 0.0) for x in items)/len(items) if items else 0.0
    tx_avg = sum((x.get("tx_kbps") or 0.0) for x in items)/len(items) if items else 0.0
    have_lat = [x.get('latency_ms') for x in items if x.get('latency_ms') is not None]
    lat_avg = (sum(have_lat)/len(have_lat)) if have_lat else 0.0
    return {"items": items, "summary": {"rx_avg": rx_avg, "tx_avg": tx_avg, "latency_avg": lat_avg}}


@router.get("/api/network/errors_hourly")
async def api_network_errors_hourly(iface: str = "__total__", hours: int = 24, user: dict = Depends(require_user)):
    since = int(time.time()) - max(1, hours) * 3600
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT ts, errin, errout FROM net_samples WHERE iface=? AND ts>=? ORDER BY ts",
            (iface, since),
        )).fetchall()
    buckets: Dict[int, Dict[str,int]] = {}
    prev = None
    for (ts, errin, errout) in rows:
        if prev is not None:
            di = max(0, int((errin or 0) - (prev[1] or 0)))
            do = max(0, int((errout or 0) - (prev[2] or 0)))
            hour = (ts // 3600) * 3600
            b = buckets.setdefault(hour, {"errin":0, "errout":0})
            b["errin"] += di; b["errout"] += do
        prev = (ts, errin or 0, errout or 0)
    now = int(time.time())
    out_items = []
    for i in range(hours-1, -1, -1):
        h = ((now // 3600) * 3600) - i*3600
        bi = buckets.get(h, {"errin":0, "errout":0})
        out_items.append({"ts": h, "errin": bi["errin"], "errout": bi["errout"], "err_total": bi["errin"]+bi["errout"]})
    return {"items": out_items}


@router.get("/api/network/errors_minutely")
async def api_network_errors_minutely(iface: str = "__total__", minutes: int = 60, user: dict = Depends(require_user)):
    since = int(time.time()) - max(1, minutes) * 60
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT ts, errin, errout FROM net_samples WHERE iface=? AND ts>=? ORDER BY ts",
            (iface, since),
        )).fetchall()
    # Aggregate per-minute increments based on deltas between consecutive samples
    buckets: Dict[int, Dict[str,int]] = {}
    prev = None
    for (ts, errin, errout) in rows:
        if prev is not None:
            di = max(0, int((errin or 0) - (prev[1] or 0)))
            do = max(0, int((errout or 0) - (prev[2] or 0)))
            minute = (ts // 60) * 60
            b = buckets.setdefault(minute, {"errin":0, "errout":0})
            b["errin"] += di; b["errout"] += do
        prev = (ts, errin or 0, errout or 0)
    now = int(time.time())
    out_items = []
    for i in range(minutes-1, -1, -1):
        m = ((now // 60) * 60) - i*60
        bi = buckets.get(m, {"errin":0, "errout":0})
        out_items.append({"ts": m, "errin": bi["errin"], "errout": bi["errout"], "err_total": bi["errin"]+bi["errout"]})
    return {"items": out_items}


# SSE: stream latest per-interface network sample for realtime charts
async def _sse_event(data: dict) -> bytes:
    buf = ""
    import json as _json
    payload = _json.dumps(data, ensure_ascii=False)
    for line in payload.splitlines():
        buf += f"data: {line}\n"
    buf += "\n"
    return buf.encode("utf-8")


@router.get("/sse/network")
async def sse_network(request: Request, iface: str = "__total__", user: dict = Depends(require_user)):
    async def event_gen():
        last_ts = 0
        while True:
            if await request.is_disconnected():
                break
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute(
                        "SELECT ts, rx_kbps, tx_kbps, latency_ms, errin, errout FROM net_data WHERE iface=? ORDER BY ts DESC LIMIT 1",
                        (iface,),
                    ) as cur:
                        row = await cur.fetchone()
                    if row:
                        ts = int(row[0])
                        if ts != last_ts:
                            last_ts = ts
                            data = {
                                "ts": ts,
                                "iface": iface,
                                "rx_kbps": row[1],
                                "tx_kbps": row[2],
                                "latency_ms": row[3],
                                "errin": row[4],
                                "errout": row[5],
                            }
                            yield await _sse_event(data)
            except Exception:
                pass
            await asyncio.sleep(1.0)
    return StreamingResponse(event_gen(), media_type="text/event-stream")
