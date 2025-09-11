import io, csv, sqlite3
import aiosqlite
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from ..deps import require_admin
from ..config import DB_PATH
from ..web import render


router = APIRouter()


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return render(request, "reports.html")


@router.get("/api/reports/metrics")
async def api_reports_metrics(since: int, until: int, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = await (await db.execute(
            "SELECT ts,cpu_percent,load1,load5,load15,processes,mem_percent,disk_mb_s,gpu_util_avg,gpu_temp_avg FROM metric_samples WHERE ts BETWEEN ? AND ? ORDER BY ts",
            (since, until),
        )).fetchall()
        items = [dict(r) for r in rows]
    cpu_avg = sum((x.get("cpu_percent") or 0) for x in items) / len(items) if items else 0.0
    mem_avg = sum((x.get("mem_percent") or 0) for x in items) / len(items) if items else 0.0
    disk_avg = sum((x.get("disk_mb_s") or 0) for x in items) / len(items) if items else 0.0
    gpu_util_avg = sum((x.get("gpu_util_avg") or 0) for x in items) / len(items) if items else 0.0
    gpu_temp_avg = sum((x.get("gpu_temp_avg") or 0) for x in items) / len(items) if items else 0.0
    procs_avg = sum((x.get("processes") or 0) for x in items) / len(items) if items else 0.0
    return {
        "items": items,
        "summary": {
            "count": len(items),
            "cpu_avg": cpu_avg,
            "mem_avg": mem_avg,
            "disk_avg": disk_avg,
            "gpu_util_avg": gpu_util_avg,
            "gpu_temp_avg": gpu_temp_avg,
            "procs_avg": procs_avg,
        },
    }


@router.get("/api/reports/metrics.csv")
async def api_reports_metrics_csv(since: int, until: int, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT ts,cpu_percent,load1,load5,load15,processes,mem_percent,disk_mb_s,gpu_util_avg,gpu_temp_avg FROM metric_samples WHERE ts BETWEEN ? AND ? ORDER BY ts",
            (since, until),
        )).fetchall()
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ts","cpu_percent","load1","load5","load15","processes"]) 
    w.writerows(rows)
    return PlainTextResponse(out.getvalue(), media_type="text/csv")

