from typing import Optional
import sqlite3
import aiosqlite
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from ..deps import require_user, require_admin
from ..config import DB_PATH
from ..web import render


router = APIRouter()


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return render(request, "logs.html")


@router.get("/api/logs")
async def api_logs_list(limit: int = 50, page: int = 1, category: Optional[str] = None, q: Optional[str] = None, since: Optional[int] = None, until: Optional[int] = None, request: Request = None, user: dict = Depends(require_user)):
    where, params = [], []
    if category: where.append("category=?"); params.append(category)
    if q: where.append("message LIKE ?"); params.append(f"%{q}%")
    if since: where.append("strftime('%s', created_at) >= ?"); params.append(since)
    if until: where.append("strftime('%s', created_at) <= ?"); params.append(until)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    offset = max(page-1,0)*limit
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(f"SELECT * FROM sys_logs{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        rows = await cur.fetchall()
        total = (await (await db.execute(f"SELECT COUNT(1) FROM sys_logs{where_sql}", tuple(params))).fetchone())[0]
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}


@router.post("/api/logs")
async def api_logs_create(payload: dict, user: dict = Depends(require_admin())):
    category = (payload or {}).get("category"); message = (payload or {}).get("message")
    if not category or not message:
        raise HTTPException(status_code=400, detail="缺少参数")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO sys_logs (category, message) VALUES (?,?)", (category, message))
        await db.commit()
    return {"ok": True}

