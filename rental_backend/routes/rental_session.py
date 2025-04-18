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
    """
    Создает новую сессию аренды для указанного типа предмета.

    :param item_type_id: Идентификатор типа предмета.
    :param background_tasks: Фоновые задачи для выполнения.
    :return: Объект RentalSessionGet с информацией о созданной сессии аренды.
    :raises NoneAvailable: Если нет доступных предметов указанного типа.
    """
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
    """
    Начинает сессию аренды, изменяя её статус на ACTIVE.

    :param session_id: Идентификатор сессии аренды.

    :return: Объект RentalSessionGet с обновленной информацией о сессии аренды.
    :raises ObjectNotFound: Если сессия с указанным идентификатором не найдена.
    """
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
    """
    Завершает сессию аренды, изменяя её статус на RETURNED. При необходимости выдает страйк.
    :param session_id: Идентификатор сессии аренды.
    :param with_strike: Флаг, указывающий, нужно ли выдать страйк.
    :param strike_reason: Причина выдачи страйка.
    :return: Объект RentalSessionGet с обновленной информацией о сессии аренды.
    :raises ObjectNotFound: Если сессия с указанным идентификатором не найдена.
    :raises InactiveSession: Если сессия не активна.
    """
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
    """
    Получает список сессий аренды для указанного пользователя.

    :param user_id: id пользователя.
    :return: Список объектов RentalSessionGet с информацией о сессиях аренды.
    """
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
    """
    Получает список сессий аренды с возможностью фильтрации по статусу.

    :param is_reserved: Флаг, показывать зарезервированные сессии.
    :param is_canceled: Флаг, показывать отмененные сессии.
    :param is_dismissed: Флаг, показывать отклоненные сессии.
    :param is_overdue: Флаг, показывать просроченные сессии.
    :param is_returned: Флаг, показывать возвращенные сессии.
    :param is_active: Флаг, показывать активные сессии.
    :return: Список объектов RentalSessionGet с информацией о сессиях аренды.
    """
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


@rental_session.get("/{session_id}", response_model=RentalSessionGet)
async def get_rental_session(session_id: int, user=Depends(UnionAuth())):
    session = RentalSession.get(id=session_id, session=db.session)
    return RentalSessionGet.model_validate(session)


# давай напишем краткое описание в функции, что она делает.
# Что-то на подобии: """Отменяет сессию в статусе reserved.
# Отменить может только сам юзер"""


@rental_session.delete("/{session_id}/cancel", response_model=RentalSessionGet)
async def cancel_rental_session(session_id: int, user=Depends(UnionAuth())):
    """Отменяет сессию в статусе RESERVED. Отменить может только сам юзер

    :param session_id: Идентификатор сессии аренды
    :raises ForbiddenAction: Если пользователь не владелец или статус не RESERVED
    :return: Объект отмененной сессии аренды 
    """
    session = RentalSession.get(id=session_id, session=db.session)

    if user.get("id") != session.user_id:
        raise ForbiddenAction(detail="User is not allowed to cancel this session.")

    if session.status != RentStatus.RESERVED:
        raise ForbiddenAction(
            detail=f"Cannot cancel session with status '{session.status}'. Only RESERVED sessions can be canceled."
        )

    updated_session = RentalSession.update(
        session=db.session,
        id=session_id,
        status=RentStatus.CANCELED,
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
    session_id: int, update_data: RentalSessionPatch, user=Depends(UnionAuth(scopes=["rental.session.admin"]))
):
    """
    Обновляет информацию о сессии аренды.

    :param session_id: Идентификатор сессии аренды.
    :param update_data: Данные для обновления сессии.
    :return: Объект RentalSessionGet с обновленной информацией о сессии аренды.
    :raises ObjectNotFound: Если сессия с указанным идентификатором не найдена.
    """
    session = RentalSession.get(id=session_id, session=db.session)
    if not session:
        raise ObjectNotFound
    # TODO сделать нормально, сейчас это плохо.
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
