import sqlite3
import aiosqlite
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..config import DB_PATH
from ..crypto import hash_password
from ..deps import require_admin
from ..utils.audit import audit_log


router = APIRouter()


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class UserUpdate(BaseModel):
    password: Optional[str] = None
    is_admin: Optional[bool] = None


@router.get("/api/users")
async def api_users_list(request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id DESC")
        rows = await cur.fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/users")
async def api_users_create(payload: UserCreate, request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
                (payload.username, hash_password(payload.password), 1 if payload.is_admin else 0),
            )
            await db.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(400, "用户名已存在")
    await audit_log(user["username"], "user_create", payload.username, request)
    return {"ok": True}


@router.post("/api/users/{uid}")
async def api_users_update(uid: int, payload: UserUpdate, request: Request, user: dict = Depends(require_admin())):
    sets, params = [], []
    if payload.password:
        sets.append("password_hash=?"); params.append(hash_password(payload.password))
    if payload.is_admin is not None:
        sets.append("is_admin=?"); params.append(1 if payload.is_admin else 0)
    if not sets:
        return {"ok": True}
    params.append(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", tuple(params))
        await db.commit()
    await audit_log(user["username"], "user_update", f"id={uid}", request)
    return {"ok": True}


@router.delete("/api/users/{uid}")
async def api_users_delete(uid: int, request: Request, user: dict = Depends(require_admin())):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE id=?", (uid,))
        await db.commit()
    await audit_log(user["username"], "user_delete", f"id={uid}", request)
    return {"ok": True}
