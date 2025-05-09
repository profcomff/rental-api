from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend import settings
from rental_backend.exceptions import ObjectNotFound
from rental_backend.models.db import Item, ItemType
from rental_backend.schemas.base import StatusResponseModel
from rental_backend.schemas.models import ItemGet, ItemPost
from rental_backend.settings import Settings, get_settings
from rental_backend.utils.action import ActionLogger


settings: Settings = get_settings()
item = APIRouter(prefix="/item", tags=["Items"])


@item.get("", response_model=list[ItemGet])
async def get_items(type_id: int = Query(None), user=Depends(UnionAuth())) -> list[ItemGet]:
    """
    Получает список предметов. Если указан type_id, возвращает только предметы с этим типом.

    :param type_id: Идентификатор типа предмета (опционально).
    :return: Список объектов ItemGet с информацией о предметах.
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

    :param item: Данные для создания нового предмета.
    :return: Объект ItemGet с информацией о созданном предмете.
    :raises ObjectNotFound: Если тип предмета с указанным type_id не найден.
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
    is_available: bool = Query(False, description="Флаг доступен ли предмет"),
    user=Depends(UnionAuth(scopes=["rental.item.patch"])),
) -> ItemGet:
    """
    Обновляет статус доступности предмета по его идентификатору.

    :param id: id предмета.
    :param is_available: Флаг, указывающий? какой статус поставить предмету.
    :return: Объект ItemGet с обновленной информацией о предмете.
    :raises ObjectNotFound: Если предмет с указанным id не найден.
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
    Удаляет предмет по его id.

    :param id: id предмета.
    :return: Объект StatusResponseModel с результатом выполнения операции.
    :raises ObjectNotFound: Если предмет с указанным идентификатором не найден.
    """
    item = Item.get(id, session=db.session)
    if item is None:
        raise ObjectNotFound(Item, id)
    Item.delete(id, session=db.session)
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
    Получает предмет по его идентификатору.
    """
    item = Item.get(id=id, session=db.session)
    return ItemGet.model_validate(item)
