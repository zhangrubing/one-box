from typing import Optional
import sqlite3
import aiosqlite
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from ..deps import require_user, require_admin
from ..config import DB_PATH
from ..web import render


router = APIRouter()


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request):
    return render(request, "alerts.html")


@router.get("/api/alerts")
async def api_alerts_list(limit: int = 100, page: int = 1, level: Optional[str] = None, ack: Optional[int] = None, request: Request = None, user: dict = Depends(require_user)):
    where, params = [], []
    if level: where.append("level=?"); params.append(level)
    if ack is not None: where.append("acknowledged=?"); params.append(1 if ack else 0)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    offset = max(page-1,0)*limit
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(f"SELECT * FROM alerts{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        rows = await cur.fetchall()
        total = (await (await db.execute(f"SELECT COUNT(1) FROM alerts{where_sql}", tuple(params))).fetchone())[0]
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}


@router.post("/api/alerts")
async def api_alerts_create(payload: dict, user: dict = Depends(require_admin())):
    level = (payload or {}).get("level"); title = (payload or {}).get("title"); message = (payload or {}).get("message", "")
    if not level or not title:
        raise HTTPException(status_code=400, detail="缺少参数")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO alerts (level, title, message) VALUES (?,?,?)", (level, title, message))
        await db.commit()
    return {"ok": True}


@router.post("/api/alerts/{aid}/ack")
async def api_alerts_ack(aid: int, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (aid,))
        await db.commit()
    return {"ok": True}


@router.delete("/api/alerts/{aid}")
async def api_alerts_delete(aid: int, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM alerts WHERE id=?", (aid,))
        await db.commit()
    return {"ok": True}

