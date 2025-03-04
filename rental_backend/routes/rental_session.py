import datetime

from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi_sqlalchemy import db

from rental_backend.exceptions import ForbiddenAction, InactiveSession, NoneAvailable, ObjectNotFound
from rental_backend.models.db import Item, ItemType, RentalSession
from rental_backend.routes.strike import create_strike
from rental_backend.schemas.models import RentalSessionGet, RentStatus, StrikePost
from rental_backend.utils.background_tasks import check_session_expiration


rental_session = APIRouter(prefix="/rental-sessions", tags=["RentalSession"])


@rental_session.post("/{item_type_id}", response_model=RentalSessionGet)
async def create_rental_session(item_type_id, background_tasks: BackgroundTasks, user=Depends(UnionAuth())):
    available_items = Item.query(session=db.session).filter(Item.type_id == item_type_id and Item.is_available).all()
    if not available_items:
        raise NoneAvailable
    session = RentalSession.create(
        session=db.session,
        user_id=user.get("id"),
        item_id=available_items[0].id,
        reservation_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        status=RentStatus.RESERVED,
    )
    Item.update(session=db.session, id=available_items[0].id, is_available=False)
    background_tasks.add_task(check_session_expiration)
    return RentalSessionGet.model_validate(session)


@rental_session.patch("/{session_id}/start", response_model=RentalSessionGet)
async def start_rental_session(session_id, user=Depends(UnionAuth(scopes=["rental.session.admin"]))):
    session = RentalSession.get(id=session_id, session=db.session)
    if not session:
        raise ObjectNotFound
    return RentalSessionGet.model_validate(
        RentalSession.update(
            session=db.session,
            id=session_id,
            status=RentStatus.ACTIVE,
            start_ts=datetime.datetime.now(tz=datetime.timezone.utc),
            admin_open_id=user.get("id"),
        )
    )


@rental_session.patch("/{session_id}/return", response_model=RentalSessionGet)
async def accept_end_rental_session(
    session_id,
    with_strike: bool = Query(False, description="Флаг, определяющий выдачу страйка"),
    strike_reason: str = Query("", description="Описание причины страйка"),
    user=Depends(UnionAuth(scopes=["rental.session.admin"])),
):
    rent_session = RentalSession.get(id=session_id, session=db.session)
    if not rent_session:
        raise ObjectNotFound
    if rent_session.status != RentStatus.ACTIVE:
        raise InactiveSession
    ended_session = RentalSession.update(
        session=db.session,
        id=session_id,
        status=RentStatus.RETURNED,
        end_ts=datetime.datetime.now(tz=datetime.timezone.utc) if not rent_session.end_ts else rent_session.end_ts,
        actual_return_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        admin_close_id=user.get("id"),
    )
    if with_strike:
        strike_info = StrikePost(
            user_id=ended_session.user_id, admin_id=user.get("id"), reason=strike_reason, session_id=rent_session.id
        )
        create_strike(strike_info, user=user)
    return RentalSessionGet.model_validate(ended_session)


@rental_session.get("/user/{user_id}", response_model=list[RentalSessionGet])
async def get_user_sessions(user_id, user=Depends(UnionAuth())):
    user_sessions = RentalSession.query(session=db.session).filter(RentalSession.user_id == user_id).all()
    return [RentalSessionGet.model_validate(user_session) for user_session in user_sessions]


@rental_session.get("", response_model=list[RentalSessionGet])
async def get_rental_sessions(
    is_reserved: bool = Query(False, description="флаг, показывать заявки"),
    is_canceled: bool = Query(False, description="Флаг, показывать отмененные"),
    is_dismissed: bool = Query(False, description="Флаг, показывать отклоненные"),
    is_overdue: bool = Query(False, description="Флаг, показывать просроченные"),
    is_returned: bool = Query(False, description="Флаг, показывать вернутые"),
    is_active: bool = Query(False, description="Флаг, показывать активные"),
    user=Depends(UnionAuth(scopes=["rental.session.admin"])),
):
    to_show = []
    if is_reserved:
        to_show.append(RentStatus.RESERVED)
    if is_canceled:
        to_show.append(RentStatus.CANCELED)
    if is_dismissed:
        to_show.append(RentStatus.DISMISSED)
    if is_overdue:
        to_show.append(RentStatus.OVERDUE)
    if is_returned:
        to_show.append(RentStatus.RETURNED)
    if is_active:
        to_show.append(RentStatus.ACTIVE)

    rent_sessions = RentalSession.query(session=db.session).filter(RentalSession.status.in_(to_show)).all()
    return [RentalSessionGet.model_validate(rent_session) for rent_session in rent_sessions]
