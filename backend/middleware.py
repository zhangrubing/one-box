from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse
import aiosqlite
from .config import DB_PATH, APP_SECRET
from .crypto import verify_token


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # bypass static
        if request.url.path.startswith("/static"):
            return await call_next(request)
        # parse cookie
        token = request.cookies.get("auth")
        request.state.user = None
        if token:
            ok, payload, _ = verify_token(token, APP_SECRET)
            if ok:
                async with aiosqlite.connect(DB_PATH) as db:
                    row = await (await db.execute(
                        "SELECT token_version, is_admin FROM users WHERE id=?",
                        (payload.get("uid", -1),)
                    )).fetchone()
                if row and row[0] == payload.get("ver", -999):
                    payload["is_admin"] = bool(row[1])
                    request.state.user = payload

        # protected page paths (HTML pages)
        protected = {
            "/", "/dashboard", "/users", "/hardware", "/gpu", "/network",
            "/storage", "/logs", "/alerts", "/operations", "/reports",
            "/audit", "/about"
        }
        if request.url.path in protected and request.state.user is None:
            return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)

