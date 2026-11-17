"""Dashboard and platform pages."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import audit

from ..deps import Principal, render, require_user

router = APIRouter()


@router.get("/")
def dashboard(request: Request, p: Principal = Depends(require_user)):
    st = request.app.state
    tiles = [{
        "platform": plat,
        "workflow_count": len(st.catalog.for_platform(plat.id)),
        "device_count": len(st.inventory.for_platform(plat.id)),
        "launch": plat.launcher and bool(st.inventory.launch_url(plat.id)),
    } for plat in st.catalog.platforms.values()]
    return render(request, "dashboard.html", principal=p, tiles=tiles)


@router.get("/p/{platform_id}")
def platform_page(platform_id: str, request: Request, p: Principal = Depends(require_user)):
    st = request.app.state
    plat = st.catalog.platforms.get(platform_id)
    if plat is None:
        raise HTTPException(404)
    devices = st.inventory.for_platform(platform_id)
    return render(request, "platform.html", principal=p, platform=plat, launch_url=st.inventory.launch_url(platform_id),
                  workflows=st.catalog.for_platform(platform_id), devices=devices)


@router.get("/launch/{platform_id}")
def launch(platform_id: str, request: Request, p: Principal = Depends(require_user)):
    """Open an external tool (e.g. Ekahau Design). Recorded in the audit log; no credentials are passed."""
    st = request.app.state
    plat = st.catalog.platforms.get(platform_id)
    item = st.catalog.innovation.get(platform_id)
    parent_uc = next(((i, u) for i in st.catalog.innovation.values() for u in i.use_cases if u.id == platform_id), None)
    if (plat is None or not plat.launcher) and item is None and parent_uc is None:
        raise HTTPException(404)
    url = st.inventory.launch_url(platform_id)
    if not url:
        fallback = (f"/inovasi/{platform_id}" if item else
                    f"/inovasi/{parent_uc[0].id}/{platform_id}" if parent_uc else f"/p/{platform_id}")
        return RedirectResponse(fallback, status_code=303)
    with st.db.conn() as c:
        audit.record(c, actor=p.username, actor_role=p.role,
                     action="innovation.launch" if (item or parent_uc) else "platform.launch", target=platform_id,
                     result="success", ip=p.ip)
    return RedirectResponse(url, status_code=303)


@router.get("/console/{device_name}")
def open_console(device_name: str, request: Request, p: Principal = Depends(require_user)):
    """Open a device's own management console (its https `console_url` from inventory.yaml).

    The browser goes straight to the device; the portal proxies nothing and passes no credentials.
    The click is recorded in the audit log (who opened which device, when).
    """
    st = request.app.state
    dev = st.inventory.get(device_name)
    if dev is None or not dev.console_url:
        raise HTTPException(404)
    with st.db.conn() as c:
        audit.record(c, actor=p.username, actor_role=p.role, action="device.console_open", target=dev.name,
                     result="success", ip=p.ip)
    return RedirectResponse(dev.console_url, status_code=303)
