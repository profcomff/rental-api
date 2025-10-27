import datetime

from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db
from sqlalchemy import case, or_
from sqlalchemy.orm import joinedload

from rental_backend.exceptions import (
    ForbiddenAction,
    InactiveSession,
    InvalidDeadline,
    NoneAvailable,
    ObjectNotFound,
    RateLimiterError,
    SessionExists,
)
from rental_backend.models.db import Item, ItemType, RentalSession, Strike
from rental_backend.schemas.base import StatusResponseModel
from rental_backend.schemas.models import (
    RentalSessionGet,
    RentalSessionPatch,
    RentStatus,
    StrikePost,
)
from rental_backend.settings import Settings, get_settings
from rental_backend.utils.action import ActionLogger


settings: Settings = get_settings()
rental_session = APIRouter(prefix="/rental-sessions", tags=["RentalSession"])

RENTAL_SESSION_EXPIRY = datetime.timedelta(minutes=settings.RENTAL_SESSION_EXPIRY_IN_MINUTES)
RENTAL_SESSION_OVERDUE = datetime.timedelta(hours=settings.RENTAL_SESSION_OVERDUE_IN_HOURS)


async def check_sessions_expiration():
    """
    Проверяет RESERVED сессии на наличие просроченных.
    Просроченным сессиям устанавливает статус EXPIRED, а item: is_available=True
    """
    rental_session_list: list[RentalSession] = (
        RentalSession.query(session=db.session)
        .filter(RentalSession.status == RentStatus.RESERVED)
        .filter(RentalSession.reservation_ts < datetime.datetime.now(tz=datetime.timezone.utc) - RENTAL_SESSION_EXPIRY)
        .all()
    )

    for rental_session in rental_session_list:
        rental_session.status = RentStatus.EXPIRED
        rental_session.item.is_available = True
        ActionLogger.log_event(
            user_id=rental_session.user_id,
            admin_id=None,
            session_id=rental_session.id,
            action_type="EXPIRE_SESSION",
            details={"status": RentStatus.EXPIRED},
        )


async def check_sessions_overdue():
    """
    Проверяет ACTIVE сессии на наличие истёкших.
    Истёкшим сессиям устанавливает статус OVERDUE
    """
    rental_session_list: list[RentalSession] = (
        RentalSession.query(session=db.session)
        .filter(RentalSession.status == RentStatus.ACTIVE)
        .filter(RentalSession.deadline_ts < datetime.datetime.now(tz=datetime.timezone.utc))
        .all()
    )
    for rental_session in rental_session_list:
        rental_session.status = RentStatus.OVERDUE
        ActionLogger.log_event(
            user_id=rental_session.user_id,
            admin_id=None,
            session_id=rental_session.id,
            action_type="OVERDUE_SESSION",
            details={"status": RentStatus.OVERDUE},
        )


@rental_session.post(
    "/{item_type_id}", response_model=RentalSessionGet, dependencies=[Depends(check_sessions_expiration)]
)
async def create_rental_session(
    item_type_id: int, user=Depends(UnionAuth(scopes=["rental.session.create"], enable_userdata=True))
):
    """
    Создает новую сессию аренды для указанного типа предмета.

    Cкоупы: `["rental.session.create"]`

    :param item_type_id: Идентификатор типа предмета.
    :raises NoneAvailable: Если нет доступных предметов указанного типа.
    :raises SessionExists: Если у пользователя уже есть сессия с указанным типом предмета.
    """
    exist_session_item: list[RentalSession] = RentalSession.query(session=db.session).filter(
        RentalSession.user_id == user.get("id"), RentalSession.item_type_id == item_type_id
    )
    blocking_session = exist_session_item.filter(
        or_(
            RentalSession.status == RentStatus.RESERVED,
            RentalSession.status == RentStatus.ACTIVE,
            RentalSession.status == RentStatus.OVERDUE,
        )
    ).first()
    if blocking_session:
        raise SessionExists(RentalSession, item_type_id)
    # rate limiter
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    cutoff_time = now - datetime.timedelta(minutes=settings.RENTAL_SESSION_CREATE_TIME_LIMITER_MINUTES)

    rate_limiter_sessions = (
        exist_session_item.filter(
            or_(RentalSession.status == RentStatus.EXPIRED, RentalSession.status == RentStatus.CANCELED),
            RentalSession.reservation_ts > cutoff_time,
        )
        .order_by(RentalSession.reservation_ts)
        .all()
    )

    if len(rate_limiter_sessions) >= settings.RENTAL_SESSION_CREATE_NUMBER_LIMITER:
        oldest_session_time = rate_limiter_sessions[0].reservation_ts
        oldest_session_time = oldest_session_time.replace(tzinfo=datetime.timezone.utc)

        reset_time = oldest_session_time + datetime.timedelta(
            minutes=settings.RENTAL_SESSION_CREATE_TIME_LIMITER_MINUTES
        )
        minutes_left = max(0, int((reset_time - now).total_seconds() / 60))
        raise RateLimiterError(item_type_id, minutes_left)

    available_item: Item = (
        Item.query(session=db.session).filter(Item.type_id == item_type_id, Item.is_available == True).first()
    )
    if not available_item:
        raise NoneAvailable(ItemType, item_type_id)
    # получаем ФИО и номер телефона из userdata
    userdata_info = user.get("userdata")
    full_name_info = list(filter(lambda x: "Полное имя" == x['param'], userdata_info))
    phone_number_info = list(filter(lambda x: "Номер телефона" == x['param'], userdata_info))
    full_name = full_name_info[0]["value"] if len(full_name_info) != 0 else None
    phone_number = phone_number_info[0]["value"] if len(phone_number_info) != 0 else None
    session = RentalSession.create(
        session=db.session,
        user_id=user.get("id"),
        item_id=available_item.id,
        reservation_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        status=RentStatus.RESERVED,
        user_phone=phone_number,
        user_fullname=full_name,
    )
    available_item.is_available = False

    ActionLogger.log_event(
        user_id=user.get("id"),
        admin_id=None,
        session_id=session.id,
        action_type="CREATE_SESSION",
        details={"item_id": session.item_id, "status": RentStatus.RESERVED},
    )

    return RentalSessionGet.model_validate(session)


def validate_deadline_ts(deadline_ts: datetime.datetime | None = Query(description="Deadline timestamp", default=None)):
    if deadline_ts and deadline_ts.replace(tzinfo=datetime.timezone.utc) <= datetime.datetime.now(
        tz=datetime.timezone.utc
    ):
        raise InvalidDeadline()
    return deadline_ts


@rental_session.patch(
    "/{session_id}/start", response_model=RentalSessionGet, dependencies=[Depends(check_sessions_expiration)]
)
async def start_rental_session(
    session_id, deadline_ts=Depends(validate_deadline_ts), user=Depends(UnionAuth(scopes=["rental.session.admin"]))
):
    """
    Starts a rental session, changing its status to ACTIVE.

    Scopes: `["rental.session.admin"]`

    - **session_id**: The ID of the rental session to start.

    Returns the updated rental session.

    Raises **ObjectNotFound** if the session with the specified ID is not found.
    """
    session: RentalSession = RentalSession.get(session_id, session=db.session)
    if not session:
        raise ObjectNotFound(RentalSession, info.session_id)
    if session.status != RentStatus.RESERVED:
        raise ForbiddenAction(RentalSession)
    info_for_update = {
        "session": db.session,
        "id": session_id,
        "status": RentStatus.ACTIVE,
        "start_ts": datetime.datetime.now(tz=datetime.timezone.utc),
        "admin_open_id": user.get("id"),
    }
    if deadline_ts:
        info_for_update["deadline_ts"] = deadline_ts
    else:
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        new_deadline = now.replace(hour=settings.BASE_OVERDUE, minute=0, second=0, microsecond=0)
        if now > new_deadline:
            new_deadline = now.replace(day=now.day + 1, hour=settings.BASE_OVERDUE, minute=0, second=0, microsecond=0)
        info_for_update["deadline_ts"] = new_deadline

    updated_session = RentalSession.update(**info_for_update)
    ActionLogger.log_event(
        user_id=session.user_id,
        admin_id=user.get("id"),
        session_id=session.id,
        action_type="START_SESSION",
        details={
            "status": RentStatus.ACTIVE,
            "deadline_ts": str(updated_session.deadline_ts),
        },
    )

    return RentalSessionGet.model_validate(updated_session)


@rental_session.patch("/{session_id}/return", response_model=RentalSessionGet)
async def accept_end_rental_session(
    session_id: int,
    with_strike: bool = Query(False, description="A flag indicating whether to issue a strike."),
    strike_reason: str = Query("", description="The reason for the strike."),
    user=Depends(UnionAuth(scopes=["rental.session.admin"])),
):
    """
    Ends a rental session, changing its status to RETURNED. Issues a strike if specified.

    Scopes: `["rental.session.admin"]`

    - **session_id**: The ID of the rental session to end.
    - **with_strike**: A flag indicating whether to issue a strike.
    - **strike_reason**: The reason for the strike.

    Returns the updated rental session.

    Raises:
    - **ObjectNotFound**: If the session with the specified ID is not found.
    - **InactiveSession**: If the session is not active.
    """
    rent_session = RentalSession.get(id=session_id, session=db.session)
    if not rent_session:
        raise ObjectNotFound(RentalSession, session_id)
    if rent_session.status != RentStatus.ACTIVE and rent_session.status != RentStatus.OVERDUE:
        raise InactiveSession(RentalSession, session_id)
    ended_session = RentalSession.update(
        session=db.session,
        id=session_id,
        status=RentStatus.RETURNED,
        end_ts=datetime.datetime.now(tz=datetime.timezone.utc) if not rent_session.end_ts else rent_session.end_ts,
        actual_return_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        admin_close_id=user.get("id"),
    )

    rent_session.item.is_available = True

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
        new_strike = Strike.create(
            session=db.session, **strike_info.model_dump(), create_ts=datetime.datetime.now(tz=datetime.timezone.utc)
        )

        ended_session.strike_id = new_strike.id
        db.session.commit()

        ActionLogger.log_event(
            user_id=strike_info.user_id,
            admin_id=user.get("id"),
            session_id=strike_info.session_id,
            action_type="CREATE_STRIKE",
            details=strike_info.model_dump(),
        )

    return RentalSessionGet.model_validate(ended_session)


@rental_session.get(
    "/{session_id}",
    response_model=RentalSessionGet,
    dependencies=[Depends(check_sessions_expiration), Depends(check_sessions_overdue)],
)
async def get_rental_session(session_id: int, user=Depends(UnionAuth(scopes=["rental.session.admin"]))):

    rental_session: RentalSession | None = (
        db.session.query(RentalSession)
        .options(joinedload(RentalSession.strike))
        .filter(RentalSession.id == session_id)
        .first()
    )

    if not rental_session:
        raise ObjectNotFound(RentalSession, session_id)

    result: RentalSessionGet = RentalSessionGet.model_validate(rental_session)
    result.strike_id = rental_session.strike.id if rental_session.strike else None
    return result


async def get_rental_sessions_common(
    db_session,
    is_reserved: bool = False,
    is_canceled: bool = False,
    is_dismissed: bool = False,
    is_overdue: bool = False,
    is_returned: bool = False,
    is_active: bool = False,
    is_expired: bool = False,
    item_type_id: int = 0,
    user_id: int = 0,
    is_admin: bool = False,
):
    to_show = []
    if is_overdue:
        to_show.append(RentStatus.OVERDUE)
    if is_active:
        to_show.append(RentStatus.ACTIVE)
    if is_expired:
        to_show.append(RentStatus.EXPIRED)
    if is_dismissed:
        to_show.append(RentStatus.DISMISSED)
    if is_canceled:
        to_show.append(RentStatus.CANCELED)
    if is_returned:
        to_show.append(RentStatus.RETURNED)
    if is_reserved:
        to_show.append(RentStatus.RESERVED)

    if not to_show:  # if everything false by default should show all
        to_show = list(RentStatus)

    query = db_session.query(RentalSession).options(joinedload(RentalSession.strike))
    query = query.filter(RentalSession.status.in_(to_show))

    if is_admin:
        status_to_show = {
            RentStatus.OVERDUE: 1,
            RentStatus.ACTIVE: 2,
            RentStatus.DISMISSED: 3,
            RentStatus.CANCELED: 4,
            RentStatus.EXPIRED: 5,
            RentStatus.RETURNED: 6,
            RentStatus.RESERVED: 7,
        }
    else:
        status_to_show = {
            RentStatus.OVERDUE: 1,
            RentStatus.RESERVED: 2,
            RentStatus.ACTIVE: 3,
            RentStatus.DISMISSED: 4,
            RentStatus.CANCELED: 5,
            RentStatus.EXPIRED: 6,
            RentStatus.RETURNED: 7,
        }
    status_order = case(status_to_show, value=RentalSession.status)
    query = query.order_by(status_order, RentalSession.reservation_ts)

    if user_id != 0:
        query = query.filter(RentalSession.user_id == user_id)
    if item_type_id != 0:
        query = query.filter(RentalSession.item_type_id == item_type_id)
    rent_sessions = query.all()
    for serssion in rent_sessions:
        serssion.strike_id = serssion.strike.id if serssion.strike else None
    return [RentalSessionGet.model_validate(session) for session in rent_sessions]


@rental_session.get(
    "",
    response_model=list[RentalSessionGet],
    dependencies=[Depends(check_sessions_expiration), Depends(check_sessions_overdue)],
)
async def get_rental_sessions(
    is_reserved: bool = Query(False, description="флаг, показывать заявки"),
    is_canceled: bool = Query(False, description="Флаг, показывать отмененные"),
    is_dismissed: bool = Query(False, description="Флаг, показывать отклоненные"),
    is_overdue: bool = Query(False, description="Флаг, показывать просроченные"),
    is_returned: bool = Query(False, description="Флаг, показывать вернутые"),
    is_active: bool = Query(False, description="Флаг, показывать активные"),
    is_expired: bool = Query(False, description="Флаг, показывать просроченные"),
    item_type_id: int = Query(0, description="ID типа предмета"),
    user_id: int = Query(0, description="User_id для получения сессий"),
    user=Depends(UnionAuth(scopes=["rental.session.admin"])),
):
    """
    Retrieves a list of rental sessions with optional status filtering.

    Scopes: `["rental.session.admin"]`

    - **is_reserved**: Filter by reserved sessions.
    - **is_canceled**: Filter by canceled sessions.
    - **is_dismissed**: Filter by dismissed sessions.
    - **is_overdue**: Filter by overdue sessions.
    - **is_returned**: Filter by returned sessions.
    - **is_active**: Filter by active sessions.
    - **is_expired**: Filter by expired sessions.
    - **user_id**: User_id to get sessions
    Returns a list of rental sessions.
    """
    return await get_rental_sessions_common(
        db_session=db.session,
        is_reserved=is_reserved,
        is_canceled=is_canceled,
        is_dismissed=is_dismissed,
        is_overdue=is_overdue,
        is_returned=is_returned,
        is_active=is_active,
        is_expired=is_expired,
        item_type_id=item_type_id,
        user_id=user_id,
        is_admin=True,
    )


@rental_session.get(
    "/user/me",
    response_model=list[RentalSessionGet],
    dependencies=[Depends(check_sessions_expiration), Depends(check_sessions_overdue)],
)
async def get_my_sessions(
    is_reserved: bool = Query(False, description="флаг, показывать заявки"),
    is_canceled: bool = Query(False, description="Флаг, показывать отмененные"),
    is_dismissed: bool = Query(False, description="Флаг, показывать отклоненные"),
    is_overdue: bool = Query(False, description="Флаг, показывать просроченные"),
    is_returned: bool = Query(False, description="Флаг, показывать вернутые"),
    is_active: bool = Query(False, description="Флаг, показывать активные"),
    is_expired: bool = Query(False, description="Флаг, показывать просроченные"),
    item_type_id: int = Query(0, description="ID типа предмета"),
    user=Depends(UnionAuth()),
):
    """
    Retrieves a list of rental sessions for the user with optional status filtering.

    - **is_reserved**: Filter by reserved sessions.
    - **is_canceled**: Filter by canceled sessions.
    - **is_dismissed**: Filter by dismissed sessions.
    - **is_overdue**: Filter by overdue sessions.
    - **is_returned**: Filter by returned sessions.
    - **is_active**: Filter by active sessions.
    - **is_expired**: Filter by expired sessions.
    Returns a list of rental sessions.
    """
    return await get_rental_sessions_common(
        db_session=db.session,
        is_reserved=is_reserved,
        is_canceled=is_canceled,
        is_dismissed=is_dismissed,
        is_overdue=is_overdue,
        is_returned=is_returned,
        is_active=is_active,
        is_expired=is_expired,
        item_type_id=item_type_id,
        user_id=user.get('id'),
    )


@rental_session.delete("/{session_id}", response_model=StatusResponseModel)
async def delete_rental_session(session_id: int, user=Depends(UnionAuth(scopes=["rental.session.admin"]))):
    """
    Deletes a session.

    Scopes: `["rental.session.admin"]`

    - **session_id**: The ID of the rental session to delete.

    Returns the deleted rental session.

    Raises **ForbiddenAction** if the session is in RESERVED or ACTIVE status.
    Raises **ObjectNotFound** if the session does not exist.
    """
    session = RentalSession.get(id=session_id, session=db.session)
    if (
        session.status == RentStatus.ACTIVE
        or session.status == RentStatus.RESERVED
        or session.status == RentStatus.OVERDUE
    ):
        raise ForbiddenAction(RentalSession)
    RentalSession.delete(id=session_id, session=db.session)
    return StatusResponseModel(
        status="Success", message="Rental session has been deleted", ru="Сессия удалена из RentalAPI"
    )


@rental_session.delete(
    "/{session_id}/cancel", response_model=RentalSessionGet, dependencies=[Depends(check_sessions_expiration)]
)
async def cancel_rental_session(session_id: int, user=Depends(UnionAuth())):
    """
    Cancels a session in the RESERVED status. Can only be canceled by the user who created it.

    - **session_id**: The ID of the rental session to cancel.

    Returns the canceled rental session.

    Raises **ForbiddenAction** if the user is not the owner or the session is not in RESERVED status.
    """
    session = RentalSession.get(id=session_id, session=db.session)

    if user.get("id") != session.user_id:
        raise ForbiddenAction(RentalSession)

    if session.status != RentStatus.RESERVED:
        raise ForbiddenAction(RentalSession)

    updated_session = RentalSession.update(
        session=db.session,
        id=session_id,
        status=RentStatus.CANCELED,
        end_ts=datetime.datetime.now(tz=datetime.timezone.utc),
    )
    session.item.is_available = True

    ActionLogger.log_event(
        user_id=user.get("id"),
        admin_id=None,
        session_id=session.id,
        action_type="CANCEL_SESSION",
        details={"status": RentStatus.CANCELED},
    )

    return RentalSessionGet.model_validate(updated_session)


@rental_session.patch("/{session_id}", response_model=RentalSessionGet)
async def update_rental_session(
    session_id: int, update_data: RentalSessionPatch, user=Depends(UnionAuth(scopes=["rental.session.admin"]))
):
    """
    Updates the information of a rental session.

    Scopes: `["rental.session.admin"]`

    - **session_id**: The ID of the rental session to update.
    - **update_data**: The data to update the session with.

    Returns the updated rental session.

    Raises **ObjectNotFound** if the session with the specified ID is not found.
    """
    session = RentalSession.get(id=session_id, session=db.session)
    if not session:
        raise ObjectNotFound(RentalSession, session_id)
    upd_data = update_data.model_dump(exclude_unset=True)

    updated_session = RentalSession.update(session=db.session, id=session_id, **upd_data)
    ActionLogger.log_event(
        user_id=session.user_id,
        admin_id=user.get("id"),
        session_id=session.id,
        action_type="UPDATE_SESSION",
        details={
            "status": session.status,
            "end_ts": (
                updated_session.end_ts.isoformat(timespec="milliseconds")
                if "end_ts" in upd_data and upd_data['end_ts'] is not None
                else None
            ),
            "actual_return_ts": (
                updated_session.actual_return_ts.isoformat(timespec="milliseconds")
                if "actual_return_ts" in upd_data and upd_data['actual_return_ts'] is not None
                else None
            ),
        },
    )

    return RentalSessionGet.model_validate(updated_session)
