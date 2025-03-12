import asyncio
import datetime

from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi_sqlalchemy import db

from rental_backend.exceptions import ForbiddenAction, InactiveSession, NoneAvailable, ObjectNotFound
from rental_backend.models.db import Item, ItemType, RentalSession
from rental_backend.routes.strike import create_strike
from rental_backend.schemas.models import RentalSessionGet, RentalSessionPatch, RentStatus, StrikePost
from rental_backend.utils.action import ActionLogger


rental_session = APIRouter(prefix="/rental-sessions", tags=["RentalSession"])

RENTAL_SESSION_EXPIRY = datetime.timedelta(minutes=10)


async def check_session_expiration(session_id: int):
    """Background task to check and expire rental sessions."""
    await asyncio.sleep(RENTAL_SESSION_EXPIRY.total_seconds())
    session = RentalSession.query(session=db.session).filter(RentalSession.id == session_id).one_or_none()
    if session and session.status == RentStatus.RESERVED:
        RentalSession.update(
            session=db.session,
            id=session_id,
            status=RentStatus.CANCELED,
        )
        Item.update(session=db.session, id=session.item_id, is_available=True)
        ActionLogger.log_event(
            user_id=session.user_id,
            admin_id=None,
            session_id=session.id,
            action_type="EXPIRE_SESSION",
            details={"status": RentStatus.CANCELED},
        )


@rental_session.post("/{item_type_id}", response_model=RentalSessionGet)
async def create_rental_session(item_type_id, background_tasks: BackgroundTasks, user=Depends(UnionAuth())):
    available_items = (
        Item.query(session=db.session).filter(Item.type_id == item_type_id, Item.is_available == True).all()
    )
    if not available_items:
        raise NoneAvailable(ItemType, item_type_id)
    session = RentalSession.create(
        session=db.session,
        user_id=user.get("id"),
        item_id=available_items[0].id,
        reservation_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        status=RentStatus.RESERVED,
    )
    Item.update(session=db.session, id=available_items[0].id, is_available=False)

    background_tasks.add_task(check_session_expiration, session.id)

    ActionLogger.log_event(
        user_id=user.get("id"),
        admin_id=None,
        session_id=session.id,
        action_type="CREATE_SESSION",
        details={"item_id": session.item_id, "status": RentStatus.RESERVED},
    )

    return RentalSessionGet.model_validate(session)


@rental_session.patch("/{session_id}/start", response_model=RentalSessionGet)
async def start_rental_session(session_id, user=Depends(UnionAuth(scopes=["rental.session.admin"]))):
    session = RentalSession.get(id=session_id, session=db.session)
    if not session:
        raise ObjectNotFound
    updated_session = RentalSession.update(
        session=db.session,
        id=session_id,
        status=RentStatus.ACTIVE,
        start_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        admin_open_id=user.get("id"),
    )

    ActionLogger.log_event(
        user_id=session.user_id,
        admin_id=user.get("id"),
        session_id=session.id,
        action_type="START_SESSION",
        details={"status": RentStatus.ACTIVE},
    )

    return RentalSessionGet.model_validate(updated_session)


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

    ActionLogger.log_event(
        user_id=rent_session.user_id,
        admin_id=user.get("id"),
        session_id=rent_session.id,
        action_type="RETURN_SESSION",
        details={"status": RentStatus.RETURNED},
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


@rental_session.get("/{session_id}", response_model=RentalSessionGet)
async def get_rental_session(session_id: int, user=Depends(UnionAuth())):
    session = RentalSession.get(id=session_id, session=db.session)

    return RentalSessionGet.model_validate(session)


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


@rental_session.delete("/{session_id}", response_model=RentalSessionGet)
async def cancel_rental_session(session_id: int, user=Depends(UnionAuth()), db: Session = Depends(get_db)):
    session = RentalSession.get(id=session_id, session=db)
    if not session:
        raise ObjectNotFound

    if session.user_id != user.id and not user.has_scope("rental.session.admin"):
        raise HTTPException()

    if session.status not in [RentStatus.RESERVED, RentStatus.ACTIVE]:
        raise HTTPException()

    # Проверка временного диапазона
    start_time = session.start_ts if session.status == RentStatus.ACTIVE else session.reservation_ts
    if (datetime.utcnow() - start_time) > timedelta(minutes=10):
        raise HTTPException()

    updated_session = RentalSession.update(
        session=db, id=session_id, status=RentStatus.CANCELED, canceled_at=datetime.utcnow()
    )
    Item.update(session=db, id=session.item_id, is_available=True)

    return RentalSessionGet.model_validate(updated_session)


@rental_session.patch("/{session_id}", response_model=RentalSessionGet)
async def update_rental_session(
    session_id: int, update_data: RentalSessionPatch, user=Depends(UnionAuth(scopes=["rental.session.admin"]))
):
    session = RentalSession.get(id=session_id, session=db.session)
    if not session:
        raise ObjectNotFound

    if update_data.status:
        session.status = update_data.status
    if update_data.end_ts:
        session.end_ts = update_data.end_ts
    if update_data.actual_return_ts:
        session.actual_return_ts = update_data.actual_return_ts
    if update_data.admin_close_id:
        session.admin_close_id = update_data.admin_close_id

    updated_session = RentalSession.update(
        session=db.session,
        id=session_id,
        status=session.status,
        end_ts=session.end_ts,
        actual_return_ts=session.actual_return_ts,
        admin_close_id=session.admin_close_id,
    )

    ActionLogger.log_event(
        user_id=session.user_id,
        admin_id=user.get("id"),
        session_id=session.id,
        action_type="UPDATE_SESSION",
        details={"status": session.status, "end_ts": session.end_ts, "actual_return_ts": session.actual_return_ts},
    )

    return RentalSessionGet.model_validate(updated_session)
