from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend import settings
from rental_backend.exceptions import ObjectNotFound
from rental_backend.models.db import Event, Item, ItemType, RentalSession, RentStatus, Strike
from rental_backend.schemas.base import StatusResponseModel
from rental_backend.schemas.models import ItemGet, ItemPost
from rental_backend.settings import Settings, get_settings
from rental_backend.utils.action import ActionLogger

settings: Settings = get_settings()
item = APIRouter(prefix="/item", tags=["Items"])


@item.get("", response_model=list[ItemGet])
async def get_items(type_id: int = Query(None), user=Depends(UnionAuth())) -> list[ItemGet]:
    """
    Возвращает список предметов. При указании `type_id` возвращаются только предметы заданного типа.

    Условия:
    - Пользователь должен быть аутентифицирован

    Скоупы:
    - отсутствуют (доступно любому авторизованному пользователю)

    Параметры:
    - `type_id` — (необязательный) идентификатор типа предмета для фильтрации

    Возвращает:
    - список объектов `Item`

    Ошибки:
    - отсутствуют
    """
    query = Item.query(session=db.session)
    if type_id is not None:
        query = query.filter(Item.type_id == type_id)
    items = query.all()
    return [ItemGet.model_validate(item) for item in items]


@item.post("", response_model=ItemGet)
async def create_item(item: ItemPost, user=Depends(UnionAuth(scopes=["rental.item.create"]))) -> ItemGet:
    """
    Создает новый предмет.

    Перед созданием проверяется, существует ли тип предмета с указанным `type_id`.
    После успешного создания действие логируется как `CREATE_ITEM`.

    Условия:
    - Пользователь должен быть аутентифицирован
    - Пользователь должен иметь право на создание предметов
    - Тип предмета с указанным `type_id` должен существовать

    Скоупы:
    - `rental.item.create`

    Параметры:
    - `item` — данные нового предмета

    Возвращает:
    - созданный объект `Item`

    Ошибки:
    - `ObjectNotFound` — тип предмета с указанным `type_id` не найден
    """
    item_type = ItemType.get(item.type_id, session=db.session)
    if item_type is None:
        raise ObjectNotFound(ItemType, item.type_id)
    new_item = Item.create(session=db.session, **item.model_dump())
    ActionLogger.log_event(
        user_id=None,
        admin_id=user.get('id'),
        session_id=None,
        action_type="CREATE_ITEM",
        details=ItemGet.model_validate(new_item).model_dump(),
    )
    return ItemGet.model_validate(new_item)


@item.patch("/{id}", response_model=ItemGet)
async def update_item(
    id: int,
    is_available: bool = Query(False, description="Flag indicating if the item is available"),
    user=Depends(UnionAuth(scopes=["rental.item.patch"])),
) -> ItemGet:
    """
    Обновляет статус доступности предмета по его идентификатору.

    Эндпоинт позволяет изменить только поле `is_available`.
    После успешного обновления действие логируется как `UPDATE_ITEM`.

    Условия:
    - Пользователь должен быть аутентифицирован
    - Пользователь должен иметь право на изменение предметов
    - Предмет с указанным `id` должен существовать

    Скоупы:
    - `rental.item.patch`

    Параметры:
    - `id` — идентификатор предмета
    - `is_available` — новое значение доступности предмета

    Возвращает:
    - обновленный объект `Item`

    Ошибки:
    - `ObjectNotFound` — предмет с указанным `id` не найден
    """
    item = Item.query(session=db.session).filter(Item.id == id).one_or_none()
    if item is not None:
        Item.update(id=item.id, session=db.session, is_available=is_available)
        ActionLogger.log_event(
            user_id=None,
            admin_id=user.get('id'),
            session_id=None,
            action_type="UPDATE_ITEM",
            details=ItemGet.model_validate(item).model_dump(),
        )
        return ItemGet.model_validate(item)
    raise ObjectNotFound(Item, id)


@item.delete("/{id}", response_model=StatusResponseModel)
async def delete_item(
    id: int, user=Depends(UnionAuth(scopes=["rental.item.delete"], allow_none=False))
) -> StatusResponseModel:
    """
    Удаляет предмет по его идентификатору.

    Перед удалением проверяется, что с предметом не связано активных,
    зарезервированных или просроченных сессий аренды.
    Если такие сессии существуют — удаление запрещено.

    При успешном удалении:
    - удаляется сам предмет
    - удаляются связанные сессии аренды (если они не помечены как удалённые)
    - удаляются связанные страйки и события
    - действие логируется как `DELETE_ITEM`

    Условия:
    - Пользователь должен быть аутентифицирован
    - Пользователь должен иметь право на удаление предметов
    - У предмета не должно быть сессий в статусах ACTIVE / RESERVED / OVERDUE

    Скоупы:
    - `rental.item.delete`

    Параметры:
    - `id` — идентификатор предмета

    Возвращает:
    - объект `StatusResponseModel` со статусом удаления

    Ошибки:
    - `ObjectNotFound` — предмет не найден или удаление запрещено из-за активных сессий
    """
    rental_sessions = db.session.query(RentalSession).filter(RentalSession.item_id == id)
    session = rental_sessions.filter(
        RentalSession.status.in_([RentStatus.ACTIVE, RentStatus.OVERDUE, RentStatus.RESERVED])
    ).one_or_none()
    if session is not None:
        raise ObjectNotFound(Item, id)
    Item.delete(id, session=db.session)
    for rental_session in rental_sessions:
        if not rental_session.is_deleted:
            RentalSession.delete(rental_session.id, session=db.session)
        strikes = db.session.query(Strike).filter(Strike.session_id == rental_session.id)
        for strike in strikes:
            Strike.delete(strike.id, session=db.session)
        events = db.session.query(Event).filter(Event.session_id == rental_session.id)
        for event in events:
            Event.delete(event.id, session=db.session)
    ActionLogger.log_event(
        user_id=None,
        admin_id=user.get('id'),
        session_id=None,
        action_type="DELETE_ITEM",
        details={"id": id},
    )
    return StatusResponseModel(status="success", message="Item успешно удален", ru="Предмет успешно удален")


@item.get("/{id}", response_model=ItemGet)
async def get_item(id: int) -> ItemGet:
    """
    Возвращает предмет по его идентификатору.

    Условия:
    - отсутствуют (доступно без авторизации)

    Скоупы:
    - отсутствуют

    Параметры:
    - `id` — идентификатор предмета

    Возвращает:
    - объект `Item`

    Ошибки:
    - возможна ошибка валидации, если предмет с указанным `id` не найден
    """
    item = Item.get(id=id, session=db.session)
    return ItemGet.model_validate(item)
