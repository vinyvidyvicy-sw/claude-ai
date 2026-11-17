"""Inovasi menu: pages that open external innovation resources (URL from inventory.yaml `launchers:`)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import Principal, render, require_user

router = APIRouter()


@router.get("/inovasi/{item_id}")
def innovation_page(item_id: str, request: Request, p: Principal = Depends(require_user)):
    st = request.app.state
    item = st.catalog.innovation.get(item_id)
    if item is None:
        raise HTTPException(404)
    return render(request, "innovation.html", principal=p, item=item, launch_url=st.inventory.launch_url(item_id))
