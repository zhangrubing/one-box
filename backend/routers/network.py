from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import psutil
from ..deps import require_user
from ..web import render


router = APIRouter()


@router.get("/network", response_class=HTMLResponse)
async def network_page(request: Request):
    return render(request, "network.html")


@router.get("/api/system/network")
async def api_system_network(request: Request, user: dict = Depends(require_user)):
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    out = {}
    for name, st in stats.items():
        o = {"isup": st.isup, "duplex": getattr(st, "duplex", None), "speed": getattr(st, "speed", None), "mtu": st.mtu, "addrs": []}
        for a in addrs.get(name, []):
            o["addrs"].append({"family": str(a.family).split(".")[-1], "address": a.address, "netmask": a.netmask, "broadcast": a.broadcast, "ptp": a.ptp})
        out[name] = o
    return out

