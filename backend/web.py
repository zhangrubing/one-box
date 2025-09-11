from fastapi.templating import Jinja2Templates
from fastapi import Request
from .config import BASE_DIR, APP_ENV


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def render(request: Request, name: str, **ctx):
    base = {"request": request, "user": getattr(request.state, 'user', None), "env": APP_ENV}
    base.update(ctx)
    return templates.TemplateResponse(name, base)

