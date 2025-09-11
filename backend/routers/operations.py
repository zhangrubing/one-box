import subprocess
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from ..deps import require_admin
from ..web import render


router = APIRouter()


@router.get("/operations", response_class=HTMLResponse)
async def operations_page(request: Request):
    return render(request, "operations.html")


ALLOWED_CMDS = {"uptime": ["uptime"], "df": ["df", "-h"]}


@router.post("/api/ops/run")
async def api_ops_run(cmd: str, user: dict = Depends(require_admin())):
    key = cmd.strip().split()[0]
    if key not in ALLOWED_CMDS:
        raise HTTPException(status_code=400, detail="命令不在白名单")
    try:
        out = subprocess.check_output(ALLOWED_CMDS[key], stderr=subprocess.STDOUT, timeout=5).decode(errors="ignore")
    except Exception as e:
        out = str(e)
    return {"output": out}
