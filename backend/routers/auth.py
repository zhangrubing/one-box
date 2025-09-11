from typing import Optional
import sqlite3
import aiosqlite
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from ..config import DB_PATH, APP_SECRET
from ..crypto import verify_password, sign_token
from ..deps import require_user
from ..utils.audit import audit_log
from ..web import render


router = APIRouter()


class LoginForm(BaseModel):
    username: str
    password: str


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render(request, "login.html")


@router.post("/api/login")
async def api_login(request: Request, form: LoginForm):
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute(
            "SELECT id, username, password_hash, is_admin, token_version FROM users WHERE username=?",
            (form.username,),
        )).fetchone()
        if not row or not verify_password(form.password, row[2]):
            await audit_log(form.username, "login_failed", "用户名或密码错误", request)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        payload = {"uid": row[0], "username": row[1], "is_admin": bool(row[3]), "ver": int(row[4])}
        token = sign_token(payload, APP_SECRET, expires_in=8 * 3600)
        resp = JSONResponse({"ok": True})
        resp.set_cookie("auth", token, httponly=True, samesite="lax", secure=False, max_age=8 * 3600, path="/")
        await audit_log(row[1], "login", "登录成功", request)
        return resp


@router.post("/api/logout")
async def api_logout(request: Request):
    user = getattr(request.state, 'user', None)
    resp = JSONResponse({"ok": True}); resp.delete_cookie("auth", path="/")
    if user:
        await audit_log(user["username"], "logout", "退出登录", request)
    return resp


@router.get("/logout")
async def logout_redirect():
    resp = RedirectResponse("/login"); resp.delete_cookie("auth", path="/"); return resp


@router.get("/api/me")
async def api_me(request: Request, user: dict = Depends(require_user)):
    return {"user": user}

