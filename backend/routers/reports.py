import io, csv, sqlite3, time, datetime
import aiosqlite
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from ..deps import require_admin
from ..config import DB_PATH
from ..web import render


router = APIRouter()


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return render(request, "reports.html")


def _parse_time(val: str | int | None) -> int | None:
    """Parse human-readable time or epoch seconds to epoch seconds.
    Accepts:
      - int/str epoch seconds
      - 'YYYY-MM-DD'
      - 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD HH:MM:SS'
      - ISO 'YYYY-MM-DDTHH:MM' or 'YYYY-MM-DDTHH:MM:SS'
    Interprets as local time.
    """
    if val is None:
        return None
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        pass
    s2 = s.replace("T", " ").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(s2, fmt)
            # local time to epoch seconds
            return int(time.mktime(dt.timetuple()))
        except Exception:
            continue
    return None


def _get_range(request: Request) -> tuple[int, int]:
    # Support either since/until or start/end
    qp = request.query_params
    since = _parse_time(qp.get("since")) or _parse_time(qp.get("start"))
    until = _parse_time(qp.get("until")) or _parse_time(qp.get("end"))
    now = int(time.time())
    if since is None and until is None:
        since = now - 3600; until = now
    elif since is None:
        since = (until or now) - 3600
    elif until is None:
        until = now
    if not isinstance(since, int) or not isinstance(until, int):
        raise HTTPException(status_code=400, detail="invalid time range")
    if since > until:
        since, until = until, since
    return since, until


@router.get("/api/reports/series")
async def api_reports_series(request: Request, user: dict = Depends(require_admin())):
    since, until = _get_range(request)
    out: dict = {"range": {"since": since, "until": until}}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        # CPU
        rows = await (await db.execute("SELECT ts,cpu_percent FROM cpu_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        out["cpu"] = [dict(r) for r in rows]
        # Load
        rows = await (await db.execute("SELECT ts,load1,load5,load15 FROM load_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        out["load"] = [dict(r) for r in rows]
        # Memory
        rows = await (await db.execute("SELECT ts,mem_percent,mem_used,mem_total FROM mem_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        out["mem"] = [dict(r) for r in rows]
        # Processes
        rows = await (await db.execute("SELECT ts,processes FROM proc_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        out["proc"] = [dict(r) for r in rows]
        # Disk IO
        rows = await (await db.execute("SELECT ts,disk_mb_s FROM diskio_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        out["diskio"] = [dict(r) for r in rows]
        # GPU
        rows = await (await db.execute("SELECT ts,gpu_util_avg,gpu_temp_avg FROM gpu_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        out["gpu"] = [dict(r) for r in rows]
        # Network total
        rows = await (await db.execute("SELECT ts,rx_kbps,tx_kbps,latency_ms FROM net_data WHERE iface='__total__' AND ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        out["net_total"] = [dict(r) for r in rows]
        # Network interfaces (names only)
        ifaces = await (await db.execute("SELECT DISTINCT iface FROM net_data WHERE iface!='__total__' ORDER BY iface")).fetchall()
        out["net_ifaces"] = [r[0] for r in ifaces]
    # simple summary
    def avg(vals):
        return (sum(vals)/len(vals)) if vals else 0.0
    out["summary"] = {
        "cpu_avg": avg([float(x.get("cpu_percent") or 0) for x in out.get("cpu") or []]),
        "mem_avg": avg([float(x.get("mem_percent") or 0) for x in out.get("mem") or []]),
        "disk_avg": avg([float(x.get("disk_mb_s") or 0) for x in out.get("diskio") or []]),
        "gpu_util_avg": avg([float(x.get("gpu_util_avg") or 0) for x in out.get("gpu") or []]),
        "gpu_temp_avg": avg([float(x.get("gpu_temp_avg") or 0) for x in out.get("gpu") or []]),
        "procs_avg": avg([float(x.get("processes") or 0) for x in out.get("proc") or []]),
        "net_rx_avg": avg([float(x.get("rx_kbps") or 0) for x in out.get("net_total") or []]),
        "net_tx_avg": avg([float(x.get("tx_kbps") or 0) for x in out.get("net_total") or []]),
        "latency_avg": avg([float(x.get("latency_ms") or 0) for x in out.get("net_total") or []]),
    }
    return out


@router.get("/api/reports/export.csv")
async def api_reports_export_csv(request: Request, metric: str, iface: str | None = None, user: dict = Depends(require_admin())):
    since, until = _get_range(request)
    metric = (metric or "").strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        hdr: list[str] = []
        rows: list[sqlite3.Row] = []
        if metric == "cpu":
            hdr = ["ts","cpu_percent"]
            rows = await (await db.execute("SELECT ts,cpu_percent FROM cpu_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        elif metric == "load":
            hdr = ["ts","load1","load5","load15"]
            rows = await (await db.execute("SELECT ts,load1,load5,load15 FROM load_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        elif metric == "mem":
            hdr = ["ts","mem_used","mem_total","mem_percent"]
            rows = await (await db.execute("SELECT ts,mem_used,mem_total,mem_percent FROM mem_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        elif metric == "proc":
            hdr = ["ts","processes"]
            rows = await (await db.execute("SELECT ts,processes FROM proc_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        elif metric == "diskio":
            hdr = ["ts","disk_mb_s"]
            rows = await (await db.execute("SELECT ts,disk_mb_s FROM diskio_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        elif metric == "gpu":
            hdr = ["ts","gpu_util_avg","gpu_temp_avg"]
            rows = await (await db.execute("SELECT ts,gpu_util_avg,gpu_temp_avg FROM gpu_data WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        elif metric in ("net","net_total"):
            if metric == "net_total":
                q = "SELECT ts,rx_kbps,tx_kbps,latency_ms FROM net_data WHERE iface='__total__' AND ts BETWEEN ? AND ? ORDER BY ts"
                hdr = ["ts","rx_kbps","tx_kbps","latency_ms"]
                rows = await (await db.execute(q, (since, until))).fetchall()
            else:
                iface = iface or ""
                if not iface:
                    raise HTTPException(status_code=400, detail="missing iface")
                q = "SELECT ts,rx_kbps,tx_kbps,errin,errout FROM net_data WHERE iface=? AND ts BETWEEN ? AND ? ORDER BY ts"
                hdr = ["ts","rx_kbps","tx_kbps","errin","errout"]
                rows = await (await db.execute(q, (iface, since, until))).fetchall()
        else:
            raise HTTPException(status_code=400, detail="unknown metric")
    sio = io.StringIO(); w = csv.writer(sio)
    w.writerow(hdr)
    for r in rows:
        w.writerow([r[k] for k in hdr])
    return PlainTextResponse(sio.getvalue(), media_type="text/csv")

