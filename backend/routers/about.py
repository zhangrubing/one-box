from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from ..web import render


router = APIRouter()


@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return render(request, "about.html")

