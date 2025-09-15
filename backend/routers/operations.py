import subprocess
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from ..deps import require_admin
from ..web import render


router = APIRouter()


@router.get("/operations", response_class=HTMLResponse)
async def operations_page(request: Request):
    return render(request, "operations.html")


# Whitelisted commands (exact keys). Only fixed argv are executed; no user args.
ALLOWED_CMDS = {
    # Basics
    "uptime": ["uptime"],
    "df -h": ["df", "-h"],
    # NVIDIA GPUs
    "nvidia-smi": ["nvidia-smi"],
    "nvidia-smi -L": ["nvidia-smi", "-L"],
    "nvidia-smi topo -m": ["nvidia-smi", "topo", "-m"],
    "nvidia-smi --query": [
        "nvidia-smi",
        "--query-gpu=name,driver_version,temperature.gpu,utilization.gpu,memory.total,memory.used,pcie.link.gen.max,pcie.link.gen.current",
        "--format=csv,noheader,nounits",
    ],
    "nvidia-smi pmon": ["nvidia-smi", "pmon", "-c", "1"],
    "nvidia-smi dmon": ["nvidia-smi", "dmon", "-c", "1"],
    # NVIDIA: Serial/UUID and ECC
    "nvidia-smi --query-serial": [
        "nvidia-smi",
        "--query-gpu=serial,uuid",
        "--format=csv,noheader,nounits",
    ],
    "nvidia-smi -q -d ECC": ["nvidia-smi", "-q", "-d", "ECC"],
    "nvidia-smi --query-ecc": [
        "nvidia-smi",
        "--query-gpu=ecc.mode.current,ecc.mode.pending",
        "--format=csv,noheader,nounits",
    ],
    # CUDA toolkit (if present)
    "nvcc --version": ["nvcc", "--version"],
    # AMD GPUs (if present)
    "rocm-smi": ["rocm-smi"],
    "rocminfo": ["rocminfo"],
    # PCI devices overview (Linux)
    "lspci": ["lspci"],
}


@router.post("/api/ops/run")
async def api_ops_run(cmd: str, user: dict = Depends(require_admin())):
    key = (cmd or "").strip()
    if key not in ALLOWED_CMDS:
        raise HTTPException(status_code=400, detail="命令不在白名单")
    try:
        out = subprocess.check_output(
            ALLOWED_CMDS[key], stderr=subprocess.STDOUT, timeout=8
        ).decode(errors="ignore")
    except Exception as e:
        out = str(e)
    return {"output": out}
