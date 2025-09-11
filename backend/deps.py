from typing import Optional
from fastapi import Request, HTTPException


def require_user(request: Request) -> dict:
    if getattr(request.state, 'user', None) is None:
        raise HTTPException(status_code=401)
    return request.state.user


def require_admin():
    async def dep(request: Request):
        u: Optional[dict] = getattr(request.state, 'user', None)
        if not u:
            raise HTTPException(status_code=401)
        if u.get("is_admin"):
            return u
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return dep

