"""Dashboard and platform pages."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import Principal, render, require_user

router = APIRouter()


@router.get("/")
def dashboard(request: Request, p: Principal = Depends(require_user)):
    st = request.app.state
    tiles = [{
        "platform": plat,
        "workflow_count": len(st.catalog.for_platform(plat.id)),
        "device_count": len(st.inventory.for_platform(plat.id)),
    } for plat in st.catalog.platforms.values()]
    return render(request, "dashboard.html", principal=p, tiles=tiles)


@router.get("/p/{platform_id}")
def platform_page(platform_id: str, request: Request, p: Principal = Depends(require_user)):
    st = request.app.state
    plat = st.catalog.platforms.get(platform_id)
    if plat is None:
        raise HTTPException(404)
    devices = st.inventory.for_platform(platform_id)
    return render(request, "platform.html", principal=p, platform=plat,
                  workflows=st.catalog.for_platform(platform_id), devices=devices)
