import asyncio, json, os, time, sqlite3, subprocess, shutil, csv, io, platform, re
from pathlib import Path
from typing import Optional, Dict, Any, List
import aiosqlite, psutil
from fastapi import FastAPI, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
from .crypto import hash_password, verify_password, sign_token, verify_token

APP_SECRET = os.environ.get("APP_SECRET", "change-this-secret")
APP_ENV = os.environ.get("APP_ENV", "v1.0")
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "app.db"

EXCLUDED_MOUNT_PREFIXES = [
    '/snap/', '/var/snap/', '/var/lib/snapd/', '/run/snapd/',
    '/var/lib/docker/', '/var/lib/containers/', '/var/lib/containerd/',
    '/var/lib/kubelet/', '/var/lib/flatpak/', '/run/user/',
    '/var/lib/lxc/', '/var/lib/lxd/', '/var/lib/libvirt/', '/var/lib/podman/'
]

app = FastAPI(title="一体机监控系统")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SCHEMA_SQL = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, token_version INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, detail TEXT, ip TEXT, ua TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL, title TEXT NOT NULL, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, acknowledged INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sys_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, message TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS metric_samples (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, cpu_percent REAL, load1 REAL, load5 REAL, load15 REAL, mem_used INTEGER, mem_total INTEGER, processes INTEGER);
'''

async def ensure_column(db, table: str, col: str, decl: str):
    try:
        cur = await db.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in await cur.fetchall()]
        if col not in cols:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    except Exception:
        pass


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await ensure_column(db, "metric_samples", "mem_percent", "REAL")
        await ensure_column(db, "metric_samples", "disk_mb_s", "REAL")
        await ensure_column(db, "metric_samples", "gpu_util_avg", "REAL")
        await ensure_column(db, "metric_samples", "gpu_temp_avg", "REAL")
        async with db.execute("SELECT COUNT(1) FROM users") as cur:
            row = await cur.fetchone()
            cnt = row[0] if row else 0
        if cnt == 0:
            await db.execute("INSERT INTO users(username,password_hash,is_admin) VALUES(?,?,1)", ("admin", hash_password("admin123")))
        await db.commit()

PREV_DISK_IO = None
PREV_DISK_PERDISK = {}
GPU_PRESENT = None

@app.on_event("startup")
async def on_startup():
    await init_db(); asyncio.create_task(_sampler())

@app.get("/ping")
async def ping(): return {"ok": True}

async def _sampler():
    interval = int(os.environ.get("SAMPLE_INTERVAL","5"))
    while True:
        try:
            snap = collect_system_snapshot()
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO metric_samples(ts,cpu_percent,load1,load5,load15,mem_used,mem_total,processes,mem_percent,disk_mb_s,gpu_util_avg,gpu_temp_avg) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (int(time.time()), snap["cpu_percent"], snap["load_avg"][0], snap["load_avg"][1], snap["load_avg"][2], int(snap["mem"]["used"]), int(snap["mem"]["total"]), snap["processes"], float(snap.get("mem_percent") or 0.0), float(snap.get("disk_mb_s") or 0.0), float(snap.get("gpu_util_avg") or 0.0), float(snap.get("gpu_temp_avg") or 0.0)))
                await db.commit()
        except Exception: pass
        await asyncio.sleep(interval)

def require_user(request: Request) -> dict:
    if request.state.user is None: raise HTTPException(status_code=401)
    return request.state.user

def require_admin():
    async def dep(request: Request):
        u = request.state.user
        if not u: raise HTTPException(status_code=401)
        if u.get("is_admin"): return u
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return dep

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/static"):
            return await call_next(request)
        token = request.cookies.get("auth")
        request.state.user = None
        if token:
            ok, payload, _ = verify_token(token, APP_SECRET)
            if ok:
                async with aiosqlite.connect(DB_PATH) as db:
                    row = await (await db.execute("SELECT token_version, is_admin FROM users WHERE id=?", (payload.get("uid",-1),))).fetchone()
                if row and row[0] == payload.get("ver", -999):
                    payload["is_admin"] = bool(row[1])
                    request.state.user = payload
        protected = {"/","/dashboard","/users","/hardware","/gpu","/network","/storage","/logs","/alerts","/operations","/reports","/audit","/about"}
        if request.url.path in protected and request.state.user is None:
            return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)
app.add_middleware(AuthMiddleware)

def render(request: Request, name: str, **ctx):
    base = {"request": request, "user": request.state.user, "env": APP_ENV}
    base.update(ctx); return templates.TemplateResponse(name, base)

async def audit_log(username: str, action: str, detail: str, request: Request):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO audit_logs (username, action, detail, ip, ua) VALUES (?,?,?,?,?)",
                         (username, action, detail, request.client.host if request.client else "", request.headers.get("user-agent","")))
        await db.commit()

# Auth
class LoginForm(BaseModel): username: str; password: str

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request): return render(request, "login.html")

@app.post("/api/login")
async def api_login(request: Request, form: LoginForm):
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("SELECT id, username, password_hash, is_admin, token_version FROM users WHERE username=?", (form.username,))).fetchone()
        if not row or not verify_password(form.password, row[2]):
            await audit_log(form.username, "login_failed", "用户名或密码错误", request); raise HTTPException(status_code=401, detail="用户名或密码错误")
        payload = {"uid": row[0], "username": row[1], "is_admin": bool(row[3]), "ver": int(row[4])}
        token = sign_token(payload, APP_SECRET, expires_in=8*3600)
        resp = JSONResponse({"ok": True}); resp.set_cookie("auth", token, httponly=True, samesite="lax", secure=False, max_age=8*3600, path="/")
        await audit_log(row[1], "login", "登录成功", request); return resp

@app.post("/api/logout")
async def api_logout(request: Request):
    user = request.state.user; resp = JSONResponse({"ok": True}); resp.delete_cookie("auth", path="/")
    if user: await audit_log(user["username"], "logout", "退出登录", request)
    return resp

@app.get("/logout")
async def logout_redirect(): resp = RedirectResponse("/login"); resp.delete_cookie("auth", path="/"); return resp

@app.get("/api/me")
async def api_me(request: Request, user: dict = Depends(require_user)): return {"user": user}

# Users CRUD
class UserCreate(BaseModel): username: str; password: str; is_admin: bool = False
class UserUpdate(BaseModel): password: Optional[str] = None; is_admin: Optional[bool] = None

@app.get("/api/users")
async def api_users_list(request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id DESC")
        rows = await cur.fetchall()
        return {"items": [dict(r) for r in rows]}

@app.post("/api/users")
async def api_users_create(payload: UserCreate, request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)", (payload.username, hash_password(payload.password), 1 if payload.is_admin else 0))
            await db.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(400, "用户名已存在")
    await audit_log(user["username"], "user_create", payload.username, request); return {"ok": True}

@app.post("/api/users/{uid}")
async def api_users_update(uid: int, payload: UserUpdate, request: Request, user: dict = Depends(require_admin())):
    sets, params = [], []
    if payload.password: sets.append("password_hash=?"); params.append(hash_password(payload.password))
    if payload.is_admin is not None: sets.append("is_admin=?"); params.append(1 if payload.is_admin else 0)
    if not sets: return {"ok": True}
    params.append(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", tuple(params)); await db.commit()
    await audit_log(user["username"], "user_update", f"id={uid}", request); return {"ok": True}

@app.delete("/api/users/{uid}")
async def api_users_delete(uid: int, request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE id=?", (uid,)); await db.commit()
    await audit_log(user["username"], "user_delete", f"id={uid}", request); return {"ok": True}

# Pages
@app.get("/", response_class=HTMLResponse)
async def root(request: Request): return RedirectResponse(url="/dashboard", status_code=302)
for path in ["dashboard","users","hardware","gpu","network","storage","logs","alerts","operations","reports","audit","about"]:
    async def page(request: Request, _path=path): return render(request, f"{_path}.html")
    app.get(f"/{path}", response_class=HTMLResponse)(page)

# --- System / Hardware helpers & APIs ---
def _cpu_model() -> str:
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo","r",encoding="utf-8",errors="ignore") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":",1)[1].strip()
        elif platform.system() == "Darwin":
            out = subprocess.check_output(["/usr/sbin/sysctl","-n","machdep.cpu.brand_string"], timeout=2).decode().strip()
            if out: return out
        elif platform.system() == "Windows":
            val = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER","").strip()
            if val: return val
    except Exception: pass
    return platform.processor() or "未知 CPU"

def _gpu_info() -> Dict[str, Any]:
    info = {"gpus": []}; nvsmi = shutil.which("nvidia-smi")
    if nvsmi:
        try:
            q = "--query-gpu=index,name,driver_version,memory.total,memory.used,temperature.gpu,utilization.gpu --format=csv,noheader,nounits"
            out = subprocess.check_output([nvsmi] + q.split(), stderr=subprocess.STDOUT, timeout=3).decode()
            for line in out.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 7:
                    info["gpus"].append({"index": int(parts[0]), "name": parts[1], "driver": parts[2], "mem_total": float(parts[3]), "mem_used": float(parts[4]), "temp": float(parts[5]), "util": float(parts[6])})
        except Exception as e: info["error"] = str(e)
    else: info["note"] = "未检测到 nvidia-smi"
    return info



def _linux_block_inflight(name: str) -> int:
    """Return current in-flight I/Os for a block device from /sys/block/*/stat.
    Returns -1 if not available."""
    try:
        base = os.path.basename(name)
        # In case name like 'sda1' read parent directory 'sda'
        if base.startswith('nvme'):
            parent = re.sub(r'p\d+$','', base)
        else:
            parent = re.sub(r'\d+$','', base)
        stat_path = f"/sys/block/{parent}/stat"
        with open(stat_path, 'r') as f:
            parts = f.read().strip().split()
        if len(parts) >= 9:
            return int(parts[8])
    except Exception:
        pass
    return -1


def _smart_info(dev_path: str) -> dict:
    """Best-effort SMART health/life info using smartctl -j. May require privileges."""
    info = {"smart_ok": None, "life_used": None, "life_left": None, "power_on_hours": None, "smart_msg": None}
    import shutil, subprocess
    sc = shutil.which('smartctl')
    if not sc:
        info["smart_msg"] = 'smartctl not found'
        return info
    try:
        out = subprocess.check_output([sc, '-a', '-j', dev_path], stderr=subprocess.STDOUT, timeout=3)
        data = json.loads(out.decode(errors='ignore'))
        # health
        st = (data.get('smart_status') or {}).get('passed')
        if st is not None:
            info['smart_ok'] = bool(st)
        # power on hours
        ptime = (data.get('power_on_time') or {}).get('hours')
        if ptime is not None:
            info['power_on_hours'] = int(ptime)
        # try NVMe percentage_used
        nvme = data.get('nvme_smart_health_information_log') or {}
        if 'percentage_used' in nvme:
            used = float(nvme.get('percentage_used') or 0)
            # Some drivers may report >100 when over-provision exceeded
            info['life_used'] = used
            info['life_left'] = max(0.0, 100.0 - used)
        # ATA/SATA attributes
        if info['life_used'] is None:
            # Scan attributes for known names
            for attr in (data.get('ata_smart_attributes') or {}).get('table', []) or []:
                name = (attr.get('name') or '').lower()
                raw = attr.get('raw') or {}
                val = raw.get('value')
                if val is None:
                    val = raw.get('string')
                # Media_Wearout_Indicator (Intel SSD), Percent_Lifetime_Remain (SAS), Wear_Leveling_Count, etc.
                if 'percent_lifetime_remain' in name:
                    try:
                        remain = float(str(val).split()[0])
                        info['life_left'] = remain
                        info['life_used'] = max(0.0, 100.0 - remain)
                        break
                    except Exception:
                        continue
                if 'media_wearout_indicator' in name or 'wear_leveling' in name:
                    try:
                        # These are often reported as a normalized value: 100 -> new, 0 -> worn-out
                        norm = float(attr.get('value') or 0)
                        # Interpret as remaining life in % if it looks like 0..100
                        if 0 <= norm <= 100:
                            info['life_left'] = norm
                            info['life_used'] = max(0.0, 100.0 - norm)
                            break
                    except Exception:
                        continue
    except Exception as e:
        info['smart_msg'] = str(e)
    return info

def collect_system_snapshot() -> Dict[str, Any]:
    cpu = psutil.cpu_percent(interval=None)
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0,0,0)
    mem = psutil.virtual_memory()._asdict()
    swap = psutil.swap_memory()._asdict()
    disks = []
    for p in psutil.disk_partitions(all=False):
        try: usage = psutil.disk_usage(p.mountpoint)._asdict()
        except Exception: usage = None
        disks.append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "usage": usage})
    net = psutil.net_io_counters(pernic=True)
    net2 = {k: {"bytes_sent": v.bytes_sent, "bytes_recv": v.bytes_recv, "packets_sent": v.packets_sent, "packets_recv": v.packets_recv} for k,v in net.items()}
    boot = psutil.boot_time(); procs = len(psutil.pids())
    # disk io MB/s
    global PREV_DISK_IO
    dio = psutil.disk_io_counters() if hasattr(psutil, 'disk_io_counters') else None
    disk_rate = 0.0
    if dio:
        cur = (dio.read_bytes + dio.write_bytes)
        now_t = time.time()
        try:
            prev = PREV_DISK_IO
            if prev:
                dt = max(0.001, now_t - prev[1])
                disk_rate = (cur - prev[0]) / dt / (1024*1024)
        except Exception:
            disk_rate = 0.0
        PREV_DISK_IO = (cur, now_t)
    # gpu averages
    g = _gpu_info(); gs = g.get('gpus') or []
    if gs:
        utils = [float(x.get('util') or 0) for x in gs]
        temps = [float(x.get('temp') or 0) for x in gs]
        gpu_util_avg = sum(utils)/len(utils)
        gpu_temp_avg = sum(temps)/len(temps)
    else:
        gpu_util_avg = 0.0; gpu_temp_avg = 0.0
    mem_percent = float(psutil.virtual_memory().percent)
    return {
        "time": int(time.time()),
        "cpu_percent": cpu,
        "load_avg": load,
        "mem": mem,
        "swap": swap,
        "disks": disks,
        "net": net2,
        "boot_time": boot,
        "processes": procs,
        "mem_percent": mem_percent,
        "disk_mb_s": disk_rate,
        "gpu_util_avg": gpu_util_avg,
        "gpu_temp_avg": gpu_temp_avg
    }

@app.get("/api/system/summary")
async def api_system_summary(request: Request, user: dict = Depends(require_user)):
    uname = platform.uname()
    os_info = {"system": uname.system, "node": uname.node, "release": uname.release, "version": uname.version, "machine": uname.machine, "processor": uname.processor or _cpu_model(), "python": platform.python_version(), "uptime": int(time.time() - psutil.boot_time())}
    freq = psutil.cpu_freq() or None
    cpu_info = {"model": _cpu_model(), "cores_physical": psutil.cpu_count(logical=False) or 0, "cores_logical": psutil.cpu_count(logical=True) or 0, "freq_current": getattr(freq,"current", None), "freq_max": getattr(freq,"max", None), "usage_percent": psutil.cpu_percent(interval=0.1), "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else (0,0,0)}
    vm = psutil.virtual_memory(); sm = psutil.swap_memory()
    mem_info = {"total": vm.total, "available": vm.available, "used": vm.used, "percent": vm.percent, "swap_total": sm.total, "swap_used": sm.used, "swap_percent": sm.percent}
    disks = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
            disks.append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "total": u.total, "used": u.used, "percent": u.percent})
        except Exception:
            disks.append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "total": None, "used": None, "percent": None})
    gpu = _gpu_info()
    return {"os": os_info, "cpu": cpu_info, "memory": mem_info, "disks": disks, "gpu": gpu}

@app.get("/api/system/gpu")
async def api_system_gpu(request: Request, user: dict = Depends(require_user)):
    return _gpu_info()

@app.get("/api/system/network")
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

def storage_detail() -> Dict[str, Any]:
    detail = {"devices": [], "partitions": []}
    # Best-effort physical devices
    if platform.system() == "Linux" and shutil.which("lsblk"):
        try:
            out = subprocess.check_output(["lsblk","-J","-o","NAME,PATH,TYPE,SIZE,MODEL,SERIAL,ROTA,TRAN,MOUNTPOINT,FSTYPE,KNAME,PKNAME"], timeout=3).decode()
            data = json.loads(out)
            def walk(node):
                # Ubuntu 22.04's lsblk -J outputs lowercase keys (e.g. "name").
                # The previous code queried uppercase keys and produced None values,
                # which rendered blank rows in the UI. Read keys case-insensitively.
                def g(k: str):
                    return (
                        node.get(k)
                        or node.get(k.lower())
                        or node.get(k.upper())
                    )
                item = {
                    "name": g("NAME"),
                    "path": g("PATH"),
                    "type": g("TYPE"),
                    "size": g("SIZE"),
                    "model": g("MODEL"),
                    "serial": g("SERIAL"),
                    "rota": g("ROTA"),
                    "tran": g("TRAN"),
                    "mountpoint": g("MOUNTPOINT"),
                    "fstype": g("FSTYPE"),
                    "kname": g("KNAME"),
                    "pkname": g("PKNAME"),
                }
                                # filter out loop devices (snap loop mounts)
                _tp = str(item.get("type") or "").lower()
                _nm = str(item.get("name") or "")
                _pth = str(item.get("path") or "")
                if _tp == "loop" or _nm.startswith("loop") or _pth.startswith("/dev/loop"):
                    return
                detail["devices"].append(item)
                children = node.get("children") or node.get("CHILDREN") or []
                for ch in children: walk(ch)
            for n in data.get("blockdevices",[]) or data.get("BLOCKDEVICES",[]) or []:
                walk(n)
        except Exception as e:
            detail["devices_error"] = str(e)
    elif platform.system() == "Windows" and shutil.which("wmic"):
        try:
            d_out = subprocess.check_output(["wmic","diskdrive","get","Name,Model,SerialNumber,Size,InterfaceType","/format:csv"], timeout=4).decode(errors="ignore")
            lines = [l.strip() for l in d_out.splitlines() if l.strip() and not l.startswith("Node,")]
            for l in lines:
                parts = l.split(",")
                if len(parts)>=6:
                    import re as _re
                    _name = parts[1]
                    m = _re.search(r"PHYSICALDRIVE(\d+)", _name, _re.I)
                    idx = int(m.group(1)) if m else None
                    kname = (f"PhysicalDrive{idx}" if idx is not None else None)
                    detail["devices"].append({"name":_name,"path":_name,"type":"disk","size":parts[4],"model":parts[2],"serial":parts[3],"tran":parts[5],"kname":kname,"pindex":idx})
        except Exception as e:
            detail["devices_error"] = str(e)
    
    # Attach IO metrics and SMART info
    try:
        import psutil as _psu
        now_t = time.time()
        perdisk = _psu.disk_io_counters(perdisk=True) or {}
        global PREV_DISK_PERDISK
        for d in detail["devices"]:
            # only physical disks, not loop
            typ = str(d.get("type") or "").lower()
            name = d.get("name") or os.path.basename(str(d.get("path") or ""))
            kname = d.get("kname") or name
            pkname = d.get("pkname") or None
            # Build candidate keys for psutil perdisk mapping
            cands = []
            for nm in filter(None, [kname, name, os.path.basename(str(d.get('path') or '')), pkname]):
                # Windows mapping: from \.\PHYSICALDRIVEX derive PhysicalDriveX/PHYSICALDRIVEX
                if nm.startswith('\\.\\') and 'PHYSICALDRIVE' in nm.upper():
                    m = re.search(r'PHYSICALDRIVE(\d+)', nm, re.I)
                    if m:
                        cand = f'PhysicalDrive{m.group(1)}'
                        cands.append(cand)
                        cands.append(cand.upper())
                        cands.append(nm)
                x = nm
                if x.startswith('nvme'):
                    x = re.sub(r'p\d+$','', x)
                else:
                    x = re.sub(r'\d+$','', x)
                cands.extend(list(dict.fromkeys([nm, x])))
            # choose a key that exists in psutil mapping
            devkey = None
            for key in cands:
                if key in perdisk:
                    devkey = key
                    break
            if devkey is None:
                devkey = cands[0] if cands else kname
            # queue depth from /sys/block/*/stat using normalized kernel name
            stat_name = devkey
            if stat_name.startswith('nvme'):
                stat_name = re.sub(r'p\d+$','', stat_name)
            else:
                stat_name = re.sub(r'\d+$','', stat_name)
            q = _linux_block_inflight(stat_name) if platform.system() == 'Linux' else -1
            # compute deltas
            io = perdisk.get(devkey)
            rMB, wMB, util = None, None, None
            if io is not None:
                prev = PREV_DISK_PERDISK.get(devkey)
                cur = (io.read_bytes, io.write_bytes, getattr(io, 'busy_time', 0), getattr(io, 'read_time', 0), getattr(io, 'write_time', 0))
                if prev:
                    dt = max(0.001, now_t - prev[-1])
                    rMB = (cur[0]-prev[0]) / dt / (1024*1024)
                    wMB = (cur[1]-prev[1]) / dt / (1024*1024)
                    # prefer busy_time; fall back to sum of read_time+write_time if busy_time not provided
                    busy_ms = (cur[2]-prev[2])
                    if busy_ms <= 0:
                        busy_ms = (cur[3]-prev[3]) + (cur[4]-prev[4])
                    busy = busy_ms / 1000.0
                    util = max(0.0, min(100.0, busy/dt*100.0))
                PREV_DISK_PERDISK[devkey] = (*cur, now_t)
            d['rmbs'] = rMB
            d['wmbs'] = wMB
            d['util_pct'] = util
            d['queue'] = q if q >= 0 else None
    except Exception:
        pass
# partitions
    for p in psutil.disk_partitions(all=True):
        if platform.system() == "Linux":
            dev = str(p.device or "")
            mp = str(p.mountpoint or "")
            # filter well-known sandbox/container bind mounts
            try:
                _mp = mp if mp.endswith('/') else mp + '/'
                if any(_mp.startswith(pref) for pref in EXCLUDED_MOUNT_PREFIXES):
                    continue
            except Exception:
                pass
            if not dev.startswith("/dev/") or dev.startswith("/dev/loop") or os.path.basename(dev).startswith("loop"):
                continue
        try:
            u = psutil.disk_usage(p.mountpoint)
            detail["partitions"].append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "opts": p.opts, "total": u.total, "used": u.used, "free": u.free, "percent": u.percent})
        except Exception:
            detail["partitions"].append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "opts": p.opts, "total": None, "used": None, "free": None, "percent": None})
    return detail

@app.get("/api/storage/detail")
async def api_storage_detail(request: Request, user: dict = Depends(require_user)):
    return storage_detail()

# Logs / Alerts / Ops / Audit / Reports
class LogCreate(BaseModel): category: str; message: str

@app.get("/api/logs")
async def api_logs_list(limit: int = 50, page: int = 1, category: Optional[str] = None, q: Optional[str] = None, since: Optional[int] = None, until: Optional[int] = None, request: Request = None, user: dict = Depends(require_user)):
    where, params = [], []
    if category: where.append("category=?"); params.append(category)
    if q: where.append("message LIKE ?"); params.append(f"%{q}%")
    if since: where.append("strftime('%s', created_at) >= ?"); params.append(since)
    if until: where.append("strftime('%s', created_at) <= ?"); params.append(until)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    offset = max(page-1,0)*limit
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(f"SELECT * FROM sys_logs{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        rows = await cur.fetchall()
        total = (await (await db.execute(f"SELECT COUNT(1) FROM sys_logs{where_sql}", tuple(params))).fetchone())[0]
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

@app.post("/api/logs")
async def api_logs_create(payload: LogCreate, request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO sys_logs (category, message) VALUES (?,?)", (payload.category, payload.message)); await db.commit()
    return {"ok": True}

class AlertCreate(BaseModel): level: str; title: str; message: Optional[str] = ""

@app.get("/api/alerts")
async def api_alerts_list(limit: int = 100, page: int = 1, level: Optional[str] = None, ack: Optional[int] = None, request: Request = None, user: dict = Depends(require_user)):
    where, params = [], []
    if level: where.append("level=?"); params.append(level)
    if ack is not None: where.append("acknowledged=?"); params.append(1 if ack else 0)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    offset = max(page-1,0)*limit
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(f"SELECT * FROM alerts{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        rows = await cur.fetchall()
        total = (await (await db.execute(f"SELECT COUNT(1) FROM alerts{where_sql}", tuple(params))).fetchone())[0]
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

@app.post("/api/alerts")
async def api_alerts_create(payload: AlertCreate, request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO alerts (level, title, message) VALUES (?,?,?)", (payload.level, payload.title, payload.message)); await db.commit()
    return {"ok": True}

@app.post("/api/alerts/{aid}/ack")
async def api_alerts_ack(aid: int, request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (aid,)); await db.commit()
    return {"ok": True}

@app.delete("/api/alerts/{aid}")
async def api_alerts_delete(aid: int, request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM alerts WHERE id=?", (aid,)); await db.commit()
    return {"ok": True}

ALLOWED_CMDS = { "uptime": ["uptime"], "df": ["df","-h"] }
@app.post("/api/ops/run")
async def api_ops_run(cmd: str = Query(...), user: dict = Depends(require_admin())):
    key = cmd.strip().split()[0]
    if key not in ALLOWED_CMDS: raise HTTPException(status_code=400, detail="命令不在白名单")
    try: out = subprocess.check_output(ALLOWED_CMDS[key], stderr=subprocess.STDOUT, timeout=5).decode(errors="ignore")
    except Exception as e: out = str(e)
    return {"output": out}

@app.get("/api/audit")
async def api_audit(user_like: Optional[str] = None, request: Request = None, user: dict = Depends(require_admin())):
    where, params = [], []
    if user_like: where.append("username LIKE ?"); params.append(f"%{user_like}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = await (await db.execute(f"SELECT * FROM audit_logs{where_sql} ORDER BY id DESC LIMIT 200", tuple(params))).fetchall()
        return {"items": [dict(r) for r in rows]}

@app.get("/api/reports/metrics")
async def api_reports_metrics(since: int, until: int, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = await (await db.execute("SELECT ts,cpu_percent,load1,load5,load15,processes,mem_percent,disk_mb_s,gpu_util_avg,gpu_temp_avg FROM metric_samples WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
        items = [dict(r) for r in rows]
        if items:
            cpu_avg = sum((x.get("cpu_percent") or 0) for x in items) / len(items)
            procs_avg = sum((x.get("processes") or 0) for x in items) / len(items)
        else:
            cpu_avg = 0.0; procs_avg = 0.0
        mem_avg = sum((x.get("mem_percent") or 0) for x in items)/len(items) if items else 0.0
        disk_avg = sum((x.get("disk_mb_s") or 0) for x in items)/len(items) if items else 0.0
        gpu_util_avg = sum((x.get("gpu_util_avg") or 0) for x in items)/len(items) if items else 0.0
        gpu_temp_avg = sum((x.get("gpu_temp_avg") or 0) for x in items)/len(items) if items else 0.0
        return {"items": items, "summary": {"count": len(items), "cpu_avg": cpu_avg, "mem_avg": mem_avg, "disk_avg": disk_avg, "gpu_util_avg": gpu_util_avg, "gpu_temp_avg": gpu_temp_avg, "procs_avg": procs_avg}}

@app.get("/api/reports/metrics.csv")
async def api_reports_metrics_csv(since: int, until: int, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute("SELECT ts,cpu_percent,load1,load5,load15,processes,mem_percent,disk_mb_s,gpu_util_avg,gpu_temp_avg FROM metric_samples WHERE ts BETWEEN ? AND ? ORDER BY ts", (since, until))).fetchall()
    out = io.StringIO(); w = csv.writer(out); w.writerow(["ts","cpu_percent","load1","load5","load15","processes"]); w.writerows(rows)
    return PlainTextResponse(out.getvalue(), media_type="text/csv")


@app.get("/api/process/top")
async def api_process_top(duration: int = 30, limit: int = 10, user: dict = Depends(require_user)):
    """Sample per-process CPU over `duration` seconds and return top `limit` items."""
    procs = {}
    for p in psutil.process_iter(attrs=["pid","name","username"]):
        try:
            p.cpu_percent(None)
            procs[p.pid] = p
        except Exception:
            pass
    await asyncio.sleep(max(1, min(duration, 120)))
    items = []
    for pid, p in list(procs.items()):
        try:
            cpu = p.cpu_percent(None)
            mem = p.memory_info().rss if p.is_running() else 0
            items.append({"pid": pid, "name": p.info.get("name") or "", "user": p.info.get("username") or "", "cpu": cpu, "mem_rss": mem, "mem_pct": p.memory_percent() if p.is_running() else 0.0})
        except Exception:
            continue
    items.sort(key=lambda x: x.get("cpu", 0), reverse=True)
    return {"items": items[:max(1, limit)]}


# SSE
async def sse_event(data: dict, event: Optional[str] = None) -> bytes:
    buf = ""
    if event: buf += f"event: {event}\n"
    payload = json.dumps(data, ensure_ascii=False)
    for line in payload.splitlines(): buf += f"data: {line}\n"
    buf += "\n"; return buf.encode("utf-8")

@app.get("/sse/metrics")
async def sse_metrics(request: Request, user: dict = Depends(require_user)):
    async def event_gen():
        while True:
            if await request.is_disconnected(): break
            snap = collect_system_snapshot()
            yield await sse_event(snap, event="metrics")
            await asyncio.sleep(1.0)
    return StreamingResponse(event_gen(), media_type="text/event-stream")


