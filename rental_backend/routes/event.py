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
    """
    Retrieves a list of events, with optional filtering.

    Scopes: `["rental.event.view"]`

    - **admin_id**: Filter events by admin ID.
    - **session_id**: Filter events by session ID.

    Returns a list of events.
    """
    query = db.session.query(Event)
    if user_id is not None:
        query = query.filter(Event.user_id == user_id)
    if admin_id is not None:
        query = query.filter(Event.admin_id == admin_id)
    if session_id is not None:
        query = query.filter(Event.session_id == session_id)
    events = query.all()
    result = [
        EventGet(
            id=event.id,
            user_id=event.user_id,
            admin_id=event.admin_id,
            session_id=event.session_id,
            action_type=event.action_type,
            details=dict(event.details),
            create_ts=event.create_ts,
        )
        for event in events
    ]
    return result
