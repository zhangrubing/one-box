import platform
import psutil
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from ..deps import require_user
from ..utils.system import _cpu_model
from ..web import render


router = APIRouter()


@router.get("/hardware", response_class=HTMLResponse)
async def hardware_page(request: Request):
    return render(request, "hardware.html")


@router.get("/api/system/summary")
async def api_system_summary(request: Request, user: dict = Depends(require_user)):
    import os as _os
    import time as _time
    uname = platform.uname()
    os_info = {
        "system": uname.system,
        "node": uname.node,
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
        "processor": uname.processor or _cpu_model(),
        "python": platform.python_version(),
        "uptime": int(_time.time() - psutil.boot_time()),
    }
    freq = psutil.cpu_freq() or None
    cpu_info = {
        "model": _cpu_model(),
        "cores_physical": psutil.cpu_count(logical=False) or 0,
        "cores_logical": psutil.cpu_count(logical=True) or 0,
        "freq_current": getattr(freq, "current", None),
        "freq_max": getattr(freq, "max", None),
        "usage_percent": psutil.cpu_percent(interval=0.1),
        "load_avg": _os.getloadavg() if hasattr(_os, "getloadavg") else (0, 0, 0),
    }
    vm = psutil.virtual_memory(); sm = psutil.swap_memory()
    mem_info = {"total": vm.total, "available": vm.available, "used": vm.used, "percent": vm.percent, "swap_total": sm.total, "swap_used": sm.used, "swap_percent": sm.percent}
    disks = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
            disks.append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "total": u.total, "used": u.used, "percent": u.percent})
        except Exception:
            disks.append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "total": None, "used": None, "percent": None})
    return {"os": os_info, "cpu": cpu_info, "memory": mem_info, "disks": disks}

