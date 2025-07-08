import datetime

from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend.exceptions import ForbiddenAction, InactiveSession, NoneAvailable, ObjectNotFound
from rental_backend.models.db import Item, ItemType, RentalSession, Strike
from rental_backend.schemas.models import RentalSessionGet, RentalSessionPatch, RentStatus, StrikePost
from rental_backend.utils.action import ActionLogger


rental_session = APIRouter(prefix="/rental-sessions", tags=["RentalSession"])

RENTAL_SESSION_EXPIRY = datetime.timedelta(minutes=10)


def check_session_expiration(rental_session: RentalSession) -> RentalSession:
    """
    Проверяет возвращаемые сессии на то просрочена ли она.
    В случае просрочки устанавливает сессии статус OVERDUE, а item: is_available=True

    :param rental_session: Сессия для проверки
    """
    if (
        rental_session
        and rental_session.status == RentStatus.RESERVED
        and rental_session.reservation_ts + RENTAL_SESSION_EXPIRY < datetime.datetime.now(tz=datetime.timezone.utc)
    ):
        rental_session.status = RentStatus.OVERDUE
        Item.update(session=db.session, id=rental_session.item_id, is_available=True)
        ActionLogger.log_event(
            user_id=rental_session.user_id,
            admin_id=None,
            session_id=rental_session.id,
            action_type="EXPIRE_SESSION",
            details={"status": RentStatus.OVERDUE},
        )
    return rental_session


@rental_session.post("/{item_type_id}", response_model=RentalSessionGet)
async def create_rental_session(item_type_id: int, user=Depends(UnionAuth())):
    """
    Создает новую сессию аренды для указанного типа предмета.

    :param item_type_id: Идентификатор типа предмета.
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

    ActionLogger.log_event(
        user_id=user.get("id"),
        admin_id=None,
        session_id=session.id,
        action_type="CREATE_SESSION",
        details={"item_id": session.item_id, "status": RentStatus.RESERVED},
    )

    return RentalSessionGet.model_validate(session)


@rental_session.patch("/{session_id}/start", response_model=RentalSessionGet)
async def start_rental_session(session_id: int, user=Depends(UnionAuth(scopes=["rental.session.admin"]))):
    """
    Начинает сессию аренды, изменяя её статус на ACTIVE.

    :param session_id: Идентификатор сессии аренды.

    :return: Объект RentalSessionGet с обновленной информацией о сессии аренды.
    :raises ObjectNotFound: Если сессия с указанным идентификатором не найдена.
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

        ActionLogger.log_event(
            user_id=strike_info.user_id,
            admin_id=user.get("id"),
            session_id=strike_info.session_id,
            action_type="CREATE_STRIKE",
            details=strike_info.model_dump(),
        )

    return RentalSessionGet.model_validate(ended_session)


@rental_session.get("/user/{user_id}", response_model=list[RentalSessionGet])
async def get_user_sessions(user_id: int, user=Depends(UnionAuth())):
    """
    Получает список сессий аренды для указанного пользователя.

    :param user_id: id пользователя.
    :return: Список объектов RentalSessionGet с информацией о сессиях аренды.
    """
    user_sessions: list[RentalSession] = (
        RentalSession.query(session=db.session).filter(RentalSession.user_id == user_id).all()
    )
    return [RentalSessionGet.model_validate(check_session_expiration(user_session)) for user_session in user_sessions]


@rental_session.get("", response_model=list[RentalSessionGet])
async def get_rental_sessions(
    is_reserved: bool = Query(False, description="Флаг, показывать заявки"),
    is_canceled: bool = Query(False, description="Флаг, показывать отмененные"),
    is_dismissed: bool = Query(False, description="Флаг, показывать отклоненные"),
    is_overdue: bool = Query(False, description="Флаг, показывать просроченные"),
    is_returned: bool = Query(False, description="Флаг, показывать возаращённые"),
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

    rent_sessions: list[RentalSession] = (
        RentalSession.query(session=db.session).filter(RentalSession.status.in_(to_show)).all()
    )
    result: list[RentalSessionGet] = []
    for rent_session in rent_sessions:
        check_session_expiration(rent_session)
        if rent_session.status == RentStatus.OVERDUE and not is_overdue:
            continue
        else:
            result.append(RentalSessionGet.model_validate(rent_session))
    return result


@rental_session.get("/{session_id}", response_model=RentalSessionGet)
async def get_rental_session(session_id: int, user=Depends(UnionAuth())):
    session = RentalSession.get(id=session_id, session=db.session)
    return RentalSessionGet.model_validate(check_session_expiration(session))


@rental_session.delete("/{session_id}/cancel", response_model=RentalSessionGet)
async def cancel_rental_session(session_id: int, user=Depends(UnionAuth())):
    """Отменяет сессию в статусе RESERVED. Отменить может только сам юзер

    :param session_id: Идентификатор сессии аренды
    :raises ForbiddenAction: Если пользователь не владелец или статус не RESERVED
    :return: Объект отмененной сессии аренды
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
        raise ObjectNotFound(RentalSession, session_id)
    check_session_expiration(session)
    upd_data = update_data.model_dump(exclude_unset=True)

    updated_session = RentalSession.update(session=db.session, id=session_id, **upd_data)
    ActionLogger.log_event(
        user_id=session.user_id,
        admin_id=user.get("id"),
        session_id=session.id,
        action_type="UPDATE_SESSION",
        details={
            "status": session.status,
            "end_ts": updated_session.end_ts.isoformat(timespec="milliseconds") if "end_ts" in upd_data else None,
            "actual_return_ts": (
                updated_session.actual_return_ts.isoformat(timespec="milliseconds")
                if "actual_return_ts" in upd_data
                else None
            ),
        },
    )

    return RentalSessionGet.model_validate(updated_session)
