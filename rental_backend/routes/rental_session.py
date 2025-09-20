import asyncio
import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi_sqlalchemy import db
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from rental_backend.exceptions import ForbiddenAction, InactiveSession, NoneAvailable, ObjectNotFound, SessionExists
from rental_backend.models.db import Item, ItemType, RentalSession, Strike
from rental_backend.schemas.models import RentalSessionGet, RentalSessionPatch, RentStatus, StrikePost
from rental_backend.utils.action import ActionLogger
from rental_backend.utils.custom_auth_check import UnionAuthChecker


rental_session = APIRouter(prefix="/rental-sessions", tags=["RentalSession"])

RENTAL_SESSION_EXPIRY = datetime.timedelta(minutes=10)


async def check_session_expiration(session_id: int):
    """
    Фоновая задача для проверки и истечения срока аренды.

    :param session_id: Идентификатор сессии аренды.
    """
    await asyncio.sleep(RENTAL_SESSION_EXPIRY.total_seconds())
    session = RentalSession.query(session=db.session).filter(RentalSession.id == session_id).one_or_none()
    if session and session.status == RentStatus.RESERVED:
        RentalSession.update(
            session=db.session,
            id=session_id,
            status=RentStatus.EXPIRED,
        )
        Item.update(session=db.session, id=session.item_id, is_available=True)
        ActionLogger.log_event(
            user_id=session.user_id,
            admin_id=None,
            session_id=session.id,
            action_type="EXPIRE_SESSION",
            details={"status": RentStatus.EXPIRED},
        )


@rental_session.post("/{item_type_id}", response_model=RentalSessionGet)
async def create_rental_session(item_type_id: int, background_tasks: BackgroundTasks, user=Depends(UnionAuthChecker())):
    """
    Создает новую сессию аренды для указанного типа предмета.
    :raises NoneAvailable: Если нет доступных предметов указанного типа.
    :raises SessionExists: Если у пользователя уже есть сессия с указанным типом предмета.
    """
    exist_session_item = (
        RentalSession.query(session=db.session)
        .filter(
            RentalSession.user_id == user.get("id"),
            RentalSession.item_type_id == item_type_id,
            or_(RentalSession.status == RentStatus.RESERVED, RentalSession.status == RentStatus.ACTIVE),
        )
        .first()
    )
    if exist_session_item:
        raise SessionExists(RentalSession, item_type_id)

    available_items = (
        Item.query(session=db.session).filter(Item.type_id == item_type_id, Item.is_available == True).first()
    )
    if not available_items:
        raise NoneAvailable(ItemType, item_type_id)

    session = RentalSession.create(
        session=db.session,
        user_id=user.get("id"),
        item_id=available_items.id,
        reservation_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        status=RentStatus.RESERVED,
        user_phone=user.get("user_phone"),
    )
    Item.update(session=db.session, id=available_items.id, is_available=False)

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
async def start_rental_session(session_id: int, user=Depends(UnionAuthChecker(scopes=["rental.session.admin"]))):
    """
    Starts a rental session, changing its status to ACTIVE.

    Scopes: `["rental.session.admin"]`

    - **session_id**: The ID of the rental session to start.

    Returns the updated rental session.

    Raises **ObjectNotFound** if the session with the specified ID is not found.
    """
    session = RentalSession.get(id=session_id, session=db.session)
    if not session:
        raise ObjectNotFound(RentalSession, session_id)
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
    session_id: int,
    with_strike: bool = Query(False, description="A flag indicating whether to issue a strike."),
    strike_reason: str = Query("", description="The reason for the strike."),
    user=Depends(UnionAuthChecker(scopes=["rental.session.admin"])),
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
    if rent_session.status != RentStatus.ACTIVE:
        raise InactiveSession(RentalSession, session_id)
    ended_session = RentalSession.update(
        session=db.session,
        id=session_id,
        status=RentStatus.RETURNED,
        end_ts=datetime.datetime.now(tz=datetime.timezone.utc) if not rent_session.end_ts else rent_session.end_ts,
        actual_return_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        admin_close_id=user.get("id"),
    )

    Item.update(id=rent_session.item_id, session=db.session, is_available=True)

    ActionLogger.log_event(
        user_id=rent_session.user_id,
        admin_id=user.get("id"),
        session_id=rent_session.id,
        action_type="RETURN_SESSION",
        details={"status": RentStatus.RETURNED},
    )

    strike_id = None

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

        strike_id = new_strike.id

    return RentalSessionGet.model_validate(ended_session)


@rental_session.get("/{session_id}", response_model=RentalSessionGet)
async def get_rental_session(session_id: int, user=Depends(UnionAuthChecker(scopes=["rental.session.admin"]))):

    result = (
        db.session.query(RentalSession)
        .options(joinedload(RentalSession.strike))
        .filter(RentalSession.id == session_id)
        .first()
    )

    if not result:
        raise ObjectNotFound(RentalSession, session_id)

    result.strike_id = result.strike.id if result.strike else None
    return RentalSessionGet.model_validate(result)


async def get_rental_sessions_common(
    db_session,
    is_reserved: bool = False,
    is_canceled: bool = False,
    is_dismissed: bool = False,
    is_overdue: bool = False,
    is_returned: bool = False,
    is_active: bool = False,
    item_type_id: int = 0,
    user_id: int = 0,
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

    if not to_show:  # if everything false by default should show all
        to_show = list(RentStatus)

    query = db_session.query(RentalSession).options(joinedload(RentalSession.strike))
    query = query.filter(RentalSession.status.in_(to_show))

    if user_id != 0:
        query = query.filter(RentalSession.user_id == user_id)
    if item_type_id != 0:
        query = query.filter(RentalSession.item_type_id == item_type_id)
    rent_sessions = query.all()
    for serssion in rent_sessions:
        serssion.strike_id = serssion.strike.id if serssion.strike else None
    return [RentalSessionGet.model_validate(session) for session in rent_sessions]


@rental_session.get("", response_model=list[RentalSessionGet])
async def get_rental_sessions(
    is_reserved: bool = Query(False, description="Filter by reserved sessions."),
    is_canceled: bool = Query(False, description="Filter by canceled sessions."),
    is_dismissed: bool = Query(False, description="Filter by dismissed sessions."),
    is_overdue: bool = Query(False, description="Filter by overdue sessions."),
    is_returned: bool = Query(False, description="Filter by returned sessions."),
    is_active: bool = Query(False, description="Filter by active sessions."),
    item_type_id: int = Query(0, description="Item_type_id to get sessions"),
    user_id: int = Query(0, description="User_id to get sessions"),
    user=Depends(UnionAuthChecker(scopes=["rental.session.admin"])),
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
        item_type_id=item_type_id,
        user_id=user_id,
    )


@rental_session.get("/user/me", response_model=list[RentalSessionGet])
async def get_my_sessions(
    is_reserved: bool = Query(False, description="флаг, показывать заявки"),
    is_canceled: bool = Query(False, description="Флаг, показывать отмененные"),
    is_dismissed: bool = Query(False, description="Флаг, показывать отклоненные"),
    is_overdue: bool = Query(False, description="Флаг, показывать просроченные"),
    is_returned: bool = Query(False, description="Флаг, показывать вернутые"),
    is_active: bool = Query(False, description="Флаг, показывать активные"),
    item_type_id: int = Query(0, description="ID типа предмета"),
    user=Depends(UnionAuthChecker()),
):
    """
    Retrieves a list of rental sessions for the user with optional status filtering.

    - **is_reserved**: Filter by reserved sessions.
    - **is_canceled**: Filter by canceled sessions.
    - **is_dismissed**: Filter by dismissed sessions.
    - **is_overdue**: Filter by overdue sessions.
    - **is_returned**: Filter by returned sessions.
    - **is_active**: Filter by active sessions.
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
        item_type_id=item_type_id,
        user_id=user.get('id'),
    )


@rental_session.delete("/{session_id}/cancel", response_model=RentalSessionGet)
async def cancel_rental_session(session_id: int, user=Depends(UnionAuthChecker())):
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
    Item.update(session=db.session, id=session.item_id, is_available=True)

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
    session_id: int, update_data: RentalSessionPatch, user=Depends(UnionAuthChecker(scopes=["rental.session.admin"]))
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
