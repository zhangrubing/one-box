import asyncio
from fastapi import APIRouter, Depends, Request
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
    async def event_gen():
        while True:
            if await request.is_disconnected():
                break
            snap = collect_system_snapshot()
            yield await sse_event(snap, event="metrics")
            await asyncio.sleep(1.0)
    return StreamingResponse(event_gen(), media_type="text/event-stream")
