import os, io, re, time, json, shutil, platform, subprocess
from typing import Dict, Any, Optional
import psutil
from ..config import EXCLUDED_MOUNT_PREFIXES


PREV_DISK_IO = None
PREV_DISK_PERDISK: Dict[str, Any] = {}
PREV_NET_PERNIC: Dict[str, Any] = {}
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


def get_machine_serial() -> Optional[str]:
    """Best-effort to get chassis/system serial number.
    Returns a string or None if not available.
    """
    try:
        sys = platform.system()
        if sys == "Linux":
            for p in (
                "/sys/class/dmi/id/product_serial",
                "/sys/devices/virtual/dmi/id/product_serial",
                "/sys/class/dmi/id/board_serial",
                "/sys/devices/virtual/dmi/id/product_uuid",
            ):
                try:
                    if os.path.exists(p):
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            val = (f.read() or "").strip()
                            if val and val.lower() != "unknown":
                                return val
                except Exception:
                    pass
            try:
                if os.path.exists("/etc/machine-id"):
                    with open("/etc/machine-id", "r", encoding="utf-8", errors="ignore") as f:
                        val = (f.read() or "").strip()
                        if val:
                            return val
            except Exception:
                pass
        elif sys == "Windows":
            try:
                out = subprocess.check_output(["wmic", "bios", "get", "serialnumber"], timeout=3).decode(errors="ignore")
                lines = [l.strip() for l in out.splitlines() if l.strip() and "serial" not in l.lower()]
                if lines:
                    return lines[0]
            except Exception:
                pass
            try:
                out = subprocess.check_output([
                    "powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_BIOS).SerialNumber"
                ], timeout=3).decode(errors="ignore")
                val = (out or "").strip()
                if val:
                    return val
            except Exception:
                pass
        elif sys == "Darwin":
            try:
                out = subprocess.check_output(["ioreg", "-l"], timeout=3).decode(errors="ignore")
                import re as _re
                m = _re.search(r'"IOPlatformSerialNumber"\s*=\s*"([^"]+)"', out)
                if m:
                    return m.group(1)
            except Exception:
                pass
            try:
                out = subprocess.check_output(["system_profiler", "SPHardwareDataType"], timeout=5).decode(errors="ignore")
                import re as _re
                m = _re.search(r"Serial Number.*: (.+)", out)
                if m:
                    return m.group(1).strip()
            except Exception:
                pass
    except Exception:
        pass
    return None


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
    net2 = {k: {"bytes_sent": v.bytes_sent, "bytes_recv": v.bytes_recv, "packets_sent": v.packets_sent, "packets_recv": v.packets_recv, "errin": getattr(v,'errin',0), "errout": getattr(v,'errout',0)} for k,v in net.items()}
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


def measure_latency_ms(host: Optional[str] = None, timeout: float = 1.0) -> Optional[float]:
    """Best-effort latency measurement to a host. Tries ping, then TCP connect.
    Returns milliseconds or None if unavailable.
    """
    host = host or os.environ.get("NET_PING_HOST", "1.1.1.1")
    try:
        if shutil.which("ping"):
            import platform as _pf
            if _pf.system() == "Windows":
                # ping -n 1 -w 1000 host
                out = subprocess.check_output(["ping","-n","1","-w",str(int(timeout*1000)), host], timeout=timeout+1).decode(errors="ignore")
            else:
                # ping -c 1 -W 1 host
                out = subprocess.check_output(["ping","-c","1","-W",str(int(timeout)), host], timeout=timeout+1).decode(errors="ignore")
            # parse time=xx ms
            import re as _re
            m = _re.search(r"time[=<]\s*([0-9]+\.?[0-9]*)\s*ms", out)
            if m:
                return float(m.group(1))
        # fallback: TCP connect
        import socket, time as _t
        start = _t.perf_counter()
        try:
            with socket.create_connection((host, 80), timeout=timeout):
                pass
            return ( _t.perf_counter() - start ) * 1000.0
        except Exception:
            return None
    except Exception:
        return None


def collect_network_rates() -> Dict[str, Any]:
    """Compute per-interface rx/tx rates (KB/s) and expose cumulative counters, plus overall aggregate.
    Uses global PREV_NET_PERNIC to compute deltas.
    """
    out: Dict[str, Any] = {"ifaces": {}, "total": {"rx_kbps": 0.0, "tx_kbps": 0.0, "errin": 0, "errout": 0}}
    try:
        stats = psutil.net_io_counters(pernic=True) or {}
        now_t = time.time()
        global PREV_NET_PERNIC
        total_rx_kbps = 0.0
        total_tx_kbps = 0.0
        total_errin = 0
        total_errout = 0
        for name, v in stats.items():
            rx = int(getattr(v, 'bytes_recv', 0)); tx = int(getattr(v, 'bytes_sent', 0))
            errin = int(getattr(v, 'errin', 0)); errout = int(getattr(v, 'errout', 0))
            prev = PREV_NET_PERNIC.get(name)
            rx_kbps = tx_kbps = 0.0
            if prev:
                dt = max(0.001, now_t - prev[2])
                rx_kbps = max(0.0, (rx - prev[0]) / dt / 1024.0)
                tx_kbps = max(0.0, (tx - prev[1]) / dt / 1024.0)
            PREV_NET_PERNIC[name] = (rx, tx, now_t, errin, errout)
            out["ifaces"][name] = {
                "rx_bytes": rx, "tx_bytes": tx,
                "errin": errin, "errout": errout,
                "rx_kbps": rx_kbps, "tx_kbps": tx_kbps,
            }
            total_rx_kbps += rx_kbps
            total_tx_kbps += tx_kbps
            total_errin += errin
            total_errout += errout
        out["total"].update({"rx_kbps": total_rx_kbps, "tx_kbps": total_tx_kbps, "errin": total_errin, "errout": total_errout})
        out["latency_ms"] = measure_latency_ms()
    except Exception:
        pass
    return out


def detect_primary_interface() -> Optional[str]:
    """Best-effort detection of the primary/default route interface name.
    Returns interface name or None if undetermined.
    """
    try:
        import platform as _pf
        sys = _pf.system()
        if sys == "Linux" and shutil.which("ip"):
            try:
                out = subprocess.check_output(["ip","route","get","1.1.1.1"], timeout=1.5).decode(errors="ignore")
                # format: '1.1.1.1 via 192.168.1.1 dev eth0 src 192.168.1.100 ...'
                import re as _re
                m = _re.search(r"\bdev\s+(\S+)", out)
                if m:
                    return m.group(1)
            except Exception:
                # fallback
                try:
                    out = subprocess.check_output(["ip","route","show","default"], timeout=1.5).decode(errors="ignore")
                    # default via 192.168.1.1 dev eth0
                    import re as _re
                    m = _re.search(r"\bdev\s+(\S+)", out)
                    if m:
                        return m.group(1)
                except Exception:
                    pass
        elif sys == "Windows":
            try:
                out = subprocess.check_output(["route","print","-4"], timeout=2.0).decode(errors="ignore")
                # Find the default route row (0.0.0.0         0.0.0.0    GATEWAY    INTERFACE IP)
                lines = [l.strip() for l in out.splitlines() if l.strip()]
                df_line = None
                for ln in lines:
                    if ln.startswith("0.0.0.0"):
                        # columns are spaced; last column is interface IP
                        parts = [p for p in ln.split() if p]
                        if len(parts) >= 4:
                            iface_ip = parts[-1]
                            # match this IP to a NIC address
                            for name, addrs in psutil.net_if_addrs().items():
                                for a in addrs:
                                    if str(a.address) == iface_ip:
                                        return name
                        df_line = ln
                        break
            except Exception:
                pass
        elif sys == "Darwin" and shutil.which("route"):
            try:
                out = subprocess.check_output(["route","-n","get","default"], timeout=1.5).decode(errors="ignore")
                for ln in out.splitlines():
                    ln = ln.strip()
                    if ln.lower().startswith("interface:"):
                        return ln.split(":",1)[1].strip()
            except Exception:
                pass
    except Exception:
        pass
    return None


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
