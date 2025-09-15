from typing import Optional, List, Dict, Any
import sqlite3, platform, shutil, subprocess, json, time, datetime, re
import aiosqlite
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from ..deps import require_user, require_admin
from ..config import DB_PATH
from ..web import render


router = APIRouter()


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return render(request, "logs.html")


def _parse_time(val: Optional[str | int]) -> Optional[int]:
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
            return int(time.mktime(dt.timetuple()))
        except Exception:
            continue
    return None


def _fmt_dt(ts: int) -> str:
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _linux_journal(limit: int, since: Optional[int], until: Optional[int], level: Optional[str], unit: Optional[str], kernel: bool, q: Optional[str]) -> List[Dict[str, Any]]:
    if not shutil.which("journalctl"):
        return _linux_logfiles(limit, q)
    args = ["journalctl", "--no-pager", "--output=short-iso"]
    # time range
    if since:
        args += ["--since", _fmt_dt(since)]
    if until:
        args += ["--until", _fmt_dt(until)]
    # priority
    if level:
        lvl = str(level).lower()
        # map common names
        mapping = {
            "emerg":"0","alert":"1","crit":"2","err":"3","error":"3","warning":"4","warn":"4","notice":"5","info":"6","debug":"7",
        }
        args += ["-p", mapping.get(lvl, lvl)]
    if unit:
        args += ["-u", unit]
    if kernel:
        args += ["-k"]
    # limit: we'll slice after reading to keep ordering
    try:
        out = subprocess.check_output(args, stderr=subprocess.STDOUT, timeout=8).decode(errors="ignore")
    except Exception as e:
        return [{"time": "", "level": "", "source": "journalctl", "message": str(e)}]
    lines = out.splitlines()
    items: List[Dict[str, Any]] = []
    # sample: 2025-09-15 10:10:12 host systemd[1]: Started ...
    for ln in lines[-max(0, min(limit, 2000)):] if not (since or until) else lines:
        if q and q.lower() not in ln.lower():
            continue
        # crude parse
        m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[^:]*:\s*(.*)$", ln)
        tstr = m.group(1) if m else ""
        rest = m.group(2) if m else ln
        # try source like 'systemd[1]:'
        src = None
        m2 = re.match(r"^([^:]+?):\s*(.*)$", rest)
        if m2:
            src = m2.group(1)
            msg = m2.group(2)
        else:
            msg = rest
        items.append({"time": tstr, "level": level or "", "source": src or "", "message": msg})
        if len(items) >= limit:
            break
    return items[-limit:]


def _linux_logfiles(limit: int, q: Optional[str]) -> List[Dict[str, Any]]:
    candidates = [
        "/var/log/syslog",
        "/var/log/messages",
        "/var/log/system.log",
        "/var/log/kern.log",
    ]
    items: List[Dict[str, Any]] = []
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-limit:]
                for ln in lines:
                    if q and q.lower() not in ln.lower():
                        continue
                    items.append({"time": "", "level": "", "source": p, "message": ln.strip()})
        except Exception:
            continue
        if items:
            break
    return items


def _windows_eventlog(limit: int, since: Optional[int], until: Optional[int], logname: str, q: Optional[str]) -> List[Dict[str, Any]]:
    # Restrict logname
    allowed = {"System", "Application", "Security"}
    logname = logname if logname in allowed else "System"
    st = _fmt_dt(since) if since else None
    et = _fmt_dt(until) if until else None
    # Build PS script
    # Simpler: use FilterHashtable literal
    script = (
        f"$fh=@{{LogName='{logname}'" + (f"; StartTime=[datetime]'{st}'" if st else "") + (f"; EndTime=[datetime]'{et}'" if et else "") + "}}; "
        f"$ev=Get-WinEvent -FilterHashtable $fh -MaxEvents {max(1, min(limit, 2000))} | Select-Object TimeCreated, Id, LevelDisplayName, ProviderName, Message | Sort-Object TimeCreated -Descending; "
        f"$ev | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.check_output(["powershell", "-NoProfile", "-Command", script], timeout=10).decode(errors="ignore")
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
    except Exception as e:
        return [{"time": "", "level": "", "source": "EventLog", "message": str(e)}]
    items: List[Dict[str, Any]] = []
    for it in (data or [])[:limit]:
        msg = (it.get("Message") or "").strip()
        if q and q.lower() not in msg.lower():
            continue
        items.append({
            "time": (it.get("TimeCreated") or "").replace("T", " ").replace("Z", ""),
            "level": it.get("LevelDisplayName") or "",
            "source": it.get("ProviderName") or "",
            "message": msg,
            "event_id": it.get("Id"),
        })
        if len(items) >= limit:
            break
    return items


@router.get("/api/oslogs")
async def api_oslogs(
    request: Request,
    limit: int = 200,
    start: Optional[str] = None,
    end: Optional[str] = None,
    level: Optional[str] = None,
    unit: Optional[str] = None,
    kernel: bool = False,
    logname: Optional[str] = None,
    q: Optional[str] = None,
    user: dict = Depends(require_user),
):
    limit = max(1, min(int(limit or 200), 1000))
    since = _parse_time(start)
    until = _parse_time(end)
    sys = platform.system()
    if sys == "Linux":
        items = _linux_journal(limit, since, until, level, unit, bool(kernel), q)
    elif sys == "Windows":
        items = _windows_eventlog(limit, since, until, (logname or "System"), q)
    else:
        # macOS or others: try log file
        items = _linux_logfiles(limit, q)
    return {"items": items, "count": len(items)}


@router.get("/api/oslogs.csv")
async def api_oslogs_csv(
    request: Request,
    limit: int = 500,
    start: Optional[str] = None,
    end: Optional[str] = None,
    level: Optional[str] = None,
    unit: Optional[str] = None,
    kernel: bool = False,
    logname: Optional[str] = None,
    q: Optional[str] = None,
    user: dict = Depends(require_user),
):
    r = await api_oslogs(request, limit, start, end, level, unit, kernel, logname, q, user)  # type: ignore
    import csv, io
    sio = io.StringIO(); w = csv.writer(sio)
    w.writerow(["time","level","source","message"])
    for it in r.get("items", []):
        w.writerow([it.get("time",""), it.get("level",""), it.get("source",""), (it.get("message","") or "").replace("\r"," ").replace("\n"," ")])
    return PlainTextResponse(sio.getvalue(), media_type="text/csv")


@router.post("/api/logs")
async def api_logs_create(payload: dict, user: dict = Depends(require_admin())):
    category = (payload or {}).get("category"); message = (payload or {}).get("message")
    if not category or not message:
        raise HTTPException(status_code=400, detail="缺少参数")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO sys_logs (category, message) VALUES (?,?)", (category, message))
        await db.commit()
    return {"ok": True}
