import aiosqlite
from fastapi import Request
from ..config import DB_PATH


async def audit_log(username: str, action: str, detail: str, request: Request):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO audit_logs (username, action, detail, ip, ua) VALUES (?,?,?,?,?)",
            (
                username,
                action,
                detail,
                request.client.host if request.client else "",
                request.headers.get("user-agent", ""),
            ),
        )
        await db.commit()

