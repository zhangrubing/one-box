import sqlite3
import aiosqlite
from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from ..deps import require_admin
from ..config import DB_PATH
from ..web import render


router = APIRouter()


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request):
    return render(request, "audit.html")


@router.get("/api/audit")
async def api_audit(user_like: Optional[str] = None, user: dict = Depends(require_admin())):
    where, params = [], []
    if user_like:
        where.append("username LIKE ?")
        params.append(f"%{user_like}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = await (await db.execute(f"SELECT * FROM audit_logs{where_sql} ORDER BY id DESC LIMIT 200", tuple(params))).fetchall()
        return {"items": [dict(r) for r in rows]}
