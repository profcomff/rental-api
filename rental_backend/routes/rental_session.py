from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from auth_lib.fastapi import UnionAuth
from fastapi_sqlalchemy import db
from rental_backend.models.db import RentalSession, Item, ItemType
from rental_backend.schemas.models import (
    RentalSessionCreate,
    RentalSessionResponse,
    RentStatus
)
from rental_backend.exceptions import ObjectNotFound, ForbiddenAction, NoneAvailable

rental_session = APIRouter(prefix="/api/rental-sessions", tags=["RentalSession"])


@rental_session.post("/{item_type_id}", response_model=RentalSessionResponse)
async def create_rental_session(item_type_id,
    user=Depends(UnionAuth(scopes=["rental.session.create"], auto_error=True))
):
    available_items = [item for item in ItemType.get(item_type_id).items if item.is_available]
    if not available_items:
        raise NoneAvailable
    session = RentalSession(user_id=user.get("id"), item_id=available_items[0], reservation_ts=datetime.datetime.now(tz=datetime.timezone.utc), status=RentStatus.RESERVED)
    return RentalSessionResponse(**session.to_dict())

@rental_session.patch("/{session_id}/start", response_model=RentalSessionResponse)
async def start_rental_session(session_id, user=Depends(UnionAuth(scopes=["rental.session.admin"]))):
    pass