from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from ..deps import require_user
from ..utils.system import storage_detail
from ..web import render


router = APIRouter()


@router.get("/storage", response_class=HTMLResponse)
async def storage_page(request: Request):
    return render(request, "storage.html")


@router.get("/api/storage/detail")
async def api_storage_detail(request: Request, user: dict = Depends(require_user)):
    return storage_detail()

