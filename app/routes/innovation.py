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
    cards = [{"uc": u, "launch": bool(st.inventory.launch_url(u.id)), "src": st.sources.get(u.id)} for u in item.use_cases]
    return render(request, "innovation.html", principal=p, item=item, cards=cards, levels=st.levels if item.use_cases else None,
                  launch_url=st.inventory.launch_url(item_id))


@router.get("/inovasi/{item_id}/{uc_id}")
def use_case_page(item_id: str, uc_id: str, request: Request, p: Principal = Depends(require_user)):
    st = request.app.state
    item = st.catalog.innovation.get(item_id)
    uc = next((u for u in (item.use_cases if item else ()) if u.id == uc_id), None)
    if uc is None:
        raise HTTPException(404)
    return render(request, "innovation_usecase.html", principal=p, item=item, uc=uc, src=st.sources.get(uc_id), levels=st.levels,
                  launch_url=st.inventory.launch_url(uc_id))


@router.get("/showcase")
def showcase(request: Request, p: Principal = Depends(require_user)):
    st = request.app.state
    cards = [{"uc": u, "item_id": i.id, "launch": bool(st.inventory.launch_url(u.id)), "src": st.sources.get(u.id)}
             for i in st.catalog.innovation.values() for u in i.use_cases]
    return render(request, "showcase.html", principal=p, cards=cards)
