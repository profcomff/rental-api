from typing import Optional

from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend.models.db import Event
from rental_backend.schemas.models import EventGet


event = APIRouter(prefix="/event", tags=["Event"])


@event.get("", response_model=list[EventGet])
async def get_events(
    user_id: Optional[int] = Query(None),
    admin_id: Optional[int] = Query(None),
    session_id: Optional[int] = Query(None),
    user=Depends(UnionAuth(scopes=["rental.event.view"], auto_error=False)),
) -> list[EventGet]:
    query = db.session.query(Event)
    if user_id is not None:
        query = query.filter(Event.user_id == user_id)
    if admin_id is not None:
        query = query.filter(Event.admin_id == admin_id)
    if session_id is not None:
        query = query.filter(Event.session_id == session_id)
    events = query.all()
    return [EventGet.model_validate(event) for event in events]
