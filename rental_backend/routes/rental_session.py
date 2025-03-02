import datetime
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

rental_session = APIRouter(prefix="/rental-sessions", tags=["RentalSession"])


@rental_session.post("/{item_type_id}", response_model=RentalSessionResponse)
async def create_rental_session(item_type_id,
    user=Depends(UnionAuth())
):
    available_items = Item.query(session=db.session).filter(Item.type_id==item_type_id and Item.is_available).all()
    if not available_items:
        raise NoneAvailable
    session = RentalSession.create(session=db.session, user_id=user.get("id"), item_id=available_items[0].id, reservation_ts=datetime.datetime.now(tz=datetime.timezone.utc), status=RentStatus.RESERVED)
    return RentalSessionResponse.model_validate(session)

@rental_session.patch("/{session_id}/start", response_model=RentalSessionResponse)
async def start_rental_session(session_id, user=Depends(UnionAuth(scopes=["rental.session.admin"]))):
    session = RentalSession.get(id=session_id, session=db.session)
    if not session:
        raise ObjectNotFound
    return RentalSessionResponse.model_validate(RentalSession.update(session=db.session, id=session_id, status=RentStatus.ACTIVE, start_ts=datetime.datetime.now(tz=datetime.timezone.utc), admin_open_id=user.get("id")))

@rental_session.patch("/{session_id}/return", response_model=RentalSessionResponse)
async def end_rental_session(session_id, user=Depends(UnionAuth(scopes=["rental.session.admin"]))):
    session = RentalSession.get(id=session_id, session=db.session)
    if not session:
        raise ObjectNotFound
    return RentalSessionResponse.model_validate(RentalSession.update(session=db.session, id=session_id, status=RentStatus.RETURNED, end_ts=datetime.datetime.now(tz=datetime.timezone.utc), admin_close_id=user.get("id")))


@rental_session.get("/user/{user_id}", response_model=list[RentalSessionResponse])
async def get_user_sessions(user_id, user=Depends(UnionAuth(scopes=["rental.session.admin"]))):
    user_sessions = RentalSession.query(session=db.session).filter(RentalSession.user_id == user_id).all()
    return [RentalSessionResponse.model_validate(user_session) for user_session in user_sessions]



