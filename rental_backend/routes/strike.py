import datetime
from typing import Optional

from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend.exceptions import DateRangeError, ObjectNotFound
from rental_backend.models.db import RentalSession, Strike
from rental_backend.schemas.base import StatusResponseModel
from rental_backend.schemas.models import StrikeGet, StrikePost
from rental_backend.utils.action import ActionLogger


strike = APIRouter(prefix="/strike", tags=["Strike"])


@strike.post("", response_model=StrikeGet)
async def create_strike(
    strike_info: StrikePost, user=Depends(UnionAuth(scopes=["rental.strike.create"], allow_none=False))
) -> StrikeGet:
    """
    Создает новый страйк.

    Перед созданием проверяется, существует ли сессия аренды с указанным `session_id`.
    После успешного создания действие логируется как `CREATE_STRIKE`.

    Условия:
    - Пользователь должен быть аутентифицирован
    - Пользователь должен иметь право на создание страйков
    - Сессия аренды с указанным `session_id` должна существовать

    Скоупы:
    - `rental.strike.create`

    Параметры:
    - `strike_info` — данные нового страйка

    Возвращает:
    - созданный объект `Strike`

    Ошибки:
    - `ObjectNotFound` — сессия аренды с указанным `session_id` не найдена
    """
    sessions = db.session.query(RentalSession).filter(RentalSession.id == strike_info.session_id).one_or_none()
    if not sessions:
        raise ObjectNotFound(RentalSession, strike_info.session_id)
    new_strike = Strike.create(
        session=db.session, **strike_info.model_dump(), create_ts=datetime.datetime.now(tz=datetime.timezone.utc)
    )
    ActionLogger.log_event(
        user_id=strike_info.user_id,
        admin_id=user.get('id'),
        session_id=strike_info.session_id,
        action_type="CREATE_STRIKE",
        details=strike_info.model_dump(),
    )
    return StrikeGet.model_validate(new_strike)


@strike.get("/user/{user_id}", response_model=list[StrikeGet])
async def get_user_strikes(user_id: int) -> list[StrikeGet]:
    """
    Возвращает список страйков пользователя по его идентификатору.

    Условия:
    - отсутствуют (доступно без авторизации)

    Скоупы:
    - отсутствуют

    Параметры:
    - `user_id` — идентификатор пользователя

    Возвращает:
    - список объектов `Strike`

    Ошибки:
    - отсутствуют
    """
    strikes = Strike.query(session=db.session).filter(Strike.user_id == user_id).all()
    return [StrikeGet.model_validate(strike) for strike in strikes]


@strike.get("", response_model=list[StrikeGet])
async def get_strikes(
    user_id: Optional[int] = Query(None),
    admin_id: Optional[int] = Query(None),
    session_id: Optional[int] = Query(None),
    from_date: Optional[datetime.datetime] = Query(None),
    to_date: Optional[datetime.datetime] = Query(None),
    user=Depends(UnionAuth(scopes=["rental.strike.read"], allow_none=False)),
) -> list[StrikeGet]:
    """
    Возвращает список страйков с возможностью фильтрации.

    Эндпоинт позволяет получить страйки и отфильтровать их по пользователю,
    администратору, сессии аренды и диапазону дат создания.

    Условия:
    - Пользователь должен быть аутентифицирован
    - Пользователь должен иметь право на просмотр страйков
    - При использовании фильтра по дате должны быть указаны оба параметра: `from_date` и `to_date`

    Скоупы:
    - `rental.strike.read`

    Параметры:
    - `user_id` — (необязательный) фильтр по идентификатору пользователя
    - `admin_id` — (необязательный) фильтр по идентификатору администратора
    - `session_id` — (необязательный) фильтр по идентификатору сессии аренды
    - `from_date` — (необязательный) начало диапазона дат создания
    - `to_date` — (необязательный) конец диапазона дат создания

    Возвращает:
    - список объектов `Strike`

    Ошибки:
    - `DateRangeError` — указан только один из параметров `from_date` или `to_date`
    """
    if (from_date is None) != (to_date is None):
        raise DateRangeError()

    query = Strike.query(session=db.session)
    if user_id is not None:
        query = query.filter(Strike.user_id == user_id)
    if admin_id is not None:
        query = query.filter(Strike.admin_id == admin_id)
    if session_id is not None:
        query = query.filter(Strike.session_id == session_id)
    if from_date is not None and to_date is not None:
        query = query.filter(Strike.create_ts.between(from_date, to_date))
    strikes = query.all()
    return [StrikeGet.model_validate(strike) for strike in strikes]


@strike.delete("/{id}", response_model=StatusResponseModel)
async def delete_strike(
    id: int, user=Depends(UnionAuth(scopes=["rental.strike.delete"], allow_none=False))
) -> StatusResponseModel:
    """
    Удаляет страйк по его идентификатору.

    Перед удалением проверяется, существует ли страйк с указанным `id`.
    После успешного удаления действие логируется как `DELETE_STRIKE`.

    Условия:
    - Пользователь должен быть аутентифицирован
    - Пользователь должен иметь право на удаление страйков
    - Страйк с указанным `id` должен существовать

    Скоупы:
    - `rental.strike.delete`

    Параметры:
    - `id` — идентификатор страйка

    Возвращает:
    - объект `StatusResponseModel` со статусом удаления

    Ошибки:
    - `ObjectNotFound` — страйк с указанным `id` не найден
    """
    strike = Strike.get(id, session=db.session)
    if strike is None:
        raise ObjectNotFound(Strike, id)
    Strike.delete(id, session=db.session)
    ActionLogger.log_event(
        user_id=strike.user_id,
        admin_id=user.get('id'),
        session_id=None,
        action_type="DELETE_STRIKE",
        details={"id": id},
    )
    return StatusResponseModel(status="success", message="Strike deleted successfully", ru="Страйк успешно удален")
