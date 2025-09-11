import os, io, re, time, json, shutil, platform, subprocess
from typing import Dict, Any, Optional
import psutil
from ..config import EXCLUDED_MOUNT_PREFIXES


PREV_DISK_IO = None
PREV_DISK_PERDISK: Dict[str, Any] = {}
GPU_PRESENT: Optional[bool] = None


def _cpu_model() -> str:
    try:
        if platform.system() == "Linux" and os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":",1)[1].strip()
        if platform.system() == "Windows":
            try:
                out = subprocess.check_output(["wmic","cpu","get","Name"], timeout=3).decode(errors="ignore")
                lines = [l.strip() for l in out.splitlines() if l.strip() and not l.lower().startswith("name")]
                if lines:
                    return lines[0]
            except Exception:
                pass
    except Exception:
        pass
    return platform.processor() or ""


def _gpu_info() -> Dict[str, Any]:
    global GPU_PRESENT
    info: Dict[str, Any] = {"gpus": []}
    try:
        if platform.system() == "Linux" and shutil.which("nvidia-smi"):
            try:
                q = ["nvidia-smi","--query-gpu=name,temperature.gpu,utilization.gpu,memory.total,memory.used,driver_version","--format=csv,noheader,nounits"]
                out = subprocess.check_output(q, timeout=3).decode(errors="ignore")
                for ln in out.splitlines():
                    parts = [x.strip() for x in ln.split(",")]
                    if len(parts) >= 6:
                        info["gpus"].append({
                            "name": parts[0],
                            "temp": float(parts[1] or 0),
                            "util": float(parts[2] or 0),
                            "mem_total": float(parts[3] or 0),
                            "mem_used": float(parts[4] or 0),
                            "driver": parts[5],
                        })
                GPU_PRESENT = True
            except Exception:
                GPU_PRESENT = False
        elif platform.system() == "Windows" and shutil.which("nvidia-smi"):
            try:
                q = ["nvidia-smi","--query-gpu=name,temperature.gpu,utilization.gpu,memory.total,memory.used,driver_version","--format=csv,noheader,nounits"]
                out = subprocess.check_output(q, timeout=3).decode(errors="ignore")
                for ln in out.splitlines():
                    parts = [x.strip() for x in ln.split(",")]
                    if len(parts) >= 6:
                        info["gpus"].append({
                            "name": parts[0],
                            "temp": float(parts[1] or 0),
                            "util": float(parts[2] or 0),
                            "mem_total": float(parts[3] or 0),
                            "mem_used": float(parts[4] or 0),
                            "driver": parts[5],
                        })
                GPU_PRESENT = True
            except Exception:
                GPU_PRESENT = False
        else:
            GPU_PRESENT = False
    except Exception:
        GPU_PRESENT = False
    return info


def collect_system_snapshot() -> Dict[str, Any]:
    cpu = psutil.cpu_percent(interval=0.1)
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0,0,0)
    vm = psutil.virtual_memory(); sm = psutil.swap_memory()
    mem = {"total": vm.total, "available": vm.available, "used": vm.used, "percent": vm.percent}
    swap = {"total": sm.total, "used": sm.used, "percent": sm.percent}
    disks = []
    for p in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(p.mountpoint)._asdict()
        except Exception:
            usage = None
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


def storage_detail() -> Dict[str, Any]:
    detail: Dict[str, Any] = {"devices": [], "partitions": []}
    # Best-effort physical devices
    if platform.system() == "Linux" and shutil.which("lsblk"):
        try:
            out = subprocess.check_output(["lsblk","-J","-o","NAME,PATH,TYPE,SIZE,MODEL,SERIAL,ROTA,TRAN,MOUNTPOINT,FSTYPE,KNAME,PKNAME"], timeout=3).decode()
            data = json.loads(out)
            def walk(node):
                # keys may vary in case across distros; accept both
                def g(k: str):
                    return node.get(k) or node.get(k.lower()) or node.get(k.upper())
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
                for ch in (node.get("children") or node.get("CHILDREN") or []):
                    walk(ch)
            for n in (data.get("blockdevices",[]) or data.get("BLOCKDEVICES",[]) or []):
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
                    _name = parts[1]
                    m = re.search(r"PHYSICALDRIVE(\d+)", _name, re.I)
                    idx = int(m.group(1)) if m else None
                    kname = (f"PhysicalDrive{idx}" if idx is not None else None)
                    detail["devices"].append({"name":_name,"path":_name,"type":"disk","size":parts[4],"model":parts[2],"serial":parts[3],"tran":parts[5],"kname":kname,"pindex":idx})
        except Exception as e:
            detail["devices_error"] = str(e)

    # partitions
    for p in psutil.disk_partitions(all=False):
        # skip system/virtual mounts
        if any(p.mountpoint.startswith(pref) for pref in EXCLUDED_MOUNT_PREFIXES):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
            detail["partitions"].append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "opts": p.opts, "total": u.total, "used": u.used, "free": u.free, "percent": u.percent})
        except Exception:
            detail["partitions"].append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "opts": p.opts, "total": None, "used": None, "free": None, "percent": None})
    return detail

