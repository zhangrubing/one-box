from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from ..web import render


router = APIRouter()


@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    return render(request, "users.html")

