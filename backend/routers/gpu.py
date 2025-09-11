from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from ..deps import require_user
from ..utils.system import _gpu_info
from ..web import render


router = APIRouter()


@router.get("/gpu", response_class=HTMLResponse)
async def gpu_page(request: Request):
    return render(request, "gpu.html")


@router.get("/api/system/gpu")
async def api_system_gpu(request: Request, user: dict = Depends(require_user)):
    return _gpu_info()

