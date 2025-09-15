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


def _check_system_alerts(snap: Dict[str, Any]) -> list:
    """检查系统告警条件并返回告警列表"""
    alerts = []
    
    # CPU 使用率告警
    cpu_percent = snap.get("cpu_percent", 0)
    if cpu_percent > 90:
        alerts.append({
            "level": "CRITICAL",
            "title": "CPU使用率过高",
            "message": f"CPU使用率达到 {cpu_percent:.1f}%，超过90%阈值"
        })
    elif cpu_percent > 80:
        alerts.append({
            "level": "WARNING", 
            "title": "CPU使用率较高",
            "message": f"CPU使用率达到 {cpu_percent:.1f}%，超过80%阈值"
        })
    
    # 内存使用率告警
    mem_percent = snap.get("mem_percent", 0)
    if mem_percent > 95:
        alerts.append({
            "level": "CRITICAL",
            "title": "内存使用率过高",
            "message": f"内存使用率达到 {mem_percent:.1f}%，超过95%阈值"
        })
    elif mem_percent > 85:
        alerts.append({
            "level": "WARNING",
            "title": "内存使用率较高", 
            "message": f"内存使用率达到 {mem_percent:.1f}%，超过85%阈值"
        })
    
    # GPU 温度告警
    gpu_temp_avg = snap.get("gpu_temp_avg", 0)
    if gpu_temp_avg > 85:
        alerts.append({
            "level": "CRITICAL",
            "title": "GPU温度过高",
            "message": f"GPU平均温度达到 {gpu_temp_avg:.1f}℃，超过85℃阈值"
        })
    elif gpu_temp_avg > 80:
        alerts.append({
            "level": "WARNING",
            "title": "GPU温度较高",
            "message": f"GPU平均温度达到 {gpu_temp_avg:.1f}℃，超过80℃阈值"
        })
    
    # 磁盘IO告警
    disk_mb_s = snap.get("disk_mb_s", 0)
    if disk_mb_s > 1000:  # 1GB/s
        alerts.append({
            "level": "WARNING",
            "title": "磁盘IO过高",
            "message": f"磁盘IO达到 {disk_mb_s:.1f} MB/s，可能影响性能"
        })
    
    # 系统负载告警
    load_avg = snap.get("load_avg", (0, 0, 0))
    cpu_count = psutil.cpu_count(logical=True) or 1
    load_1min = load_avg[0] if len(load_avg) > 0 else 0
    if load_1min > cpu_count * 2:
        alerts.append({
            "level": "WARNING",
            "title": "系统负载过高",
            "message": f"1分钟平均负载 {load_1min:.2f}，超过CPU核心数({cpu_count})的2倍"
        })
    
    return alerts


def _get_network_io() -> Dict[str, Any]:
    """获取网络IO统计"""
    try:
        net_io = psutil.net_io_counters(pernic=True)
        net_stats = {}
        for interface, stats in net_io.items():
            net_stats[interface] = {
                "bytes_sent": stats.bytes_sent,
                "bytes_recv": stats.bytes_recv,
                "packets_sent": stats.packets_sent,
                "packets_recv": stats.packets_recv,
                "errin": stats.errin,
                "errout": stats.errout,
                "dropin": stats.dropin,
                "dropout": stats.dropout
            }
        return net_stats
    except Exception:
        return {}


def _get_process_info() -> Dict[str, Any]:
    """获取进程统计信息"""
    try:
        processes = list(psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'status']))
        process_count = len(processes)
        
        # 统计各状态进程数量
        status_count = {}
        for proc in processes:
            try:
                status = proc.info.get('status', 'unknown')
                status_count[status] = status_count.get(status, 0) + 1
            except Exception:
                pass
        
        # 获取CPU和内存使用率最高的进程
        top_cpu = []
        top_memory = []
        for proc in processes:
            try:
                cpu_percent = proc.info.get('cpu_percent', 0)
                memory_percent = proc.info.get('memory_percent', 0)
                if cpu_percent > 0:
                    top_cpu.append({
                        'pid': proc.info.get('pid'),
                        'name': proc.info.get('name'),
                        'cpu_percent': cpu_percent
                    })
                if memory_percent > 0:
                    top_memory.append({
                        'pid': proc.info.get('pid'),
                        'name': proc.info.get('name'),
                        'memory_percent': memory_percent
                    })
            except Exception:
                pass
        
        # 排序并取前5
        top_cpu.sort(key=lambda x: x['cpu_percent'], reverse=True)
        top_memory.sort(key=lambda x: x['memory_percent'], reverse=True)
        
        return {
            "total": process_count,
            "status_count": status_count,
            "top_cpu": top_cpu[:5],
            "top_memory": top_memory[:5]
        }
    except Exception:
        return {"total": 0, "status_count": {}, "top_cpu": [], "top_memory": []}


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
    
    # 收集更多监控数据
    network_io = _get_network_io()
    process_info = _get_process_info()
    
    snapshot = {
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
        "gpu_temp_avg": gpu_temp_avg,
        "network_io": network_io,
        "process_info": process_info
    }
    
    # 检查告警条件
    alerts = _check_system_alerts(snapshot)
    snapshot["alerts"] = alerts
    
    return snapshot


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
