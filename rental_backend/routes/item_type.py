import datetime
from collections import defaultdict

from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends
from fastapi_sqlalchemy import db
from sqlalchemy import and_
from sqlalchemy.orm import load_only

from rental_backend.exceptions import ForbiddenAction, ObjectNotFound, ValueError
from rental_backend.models.db import Item, ItemType, RentalSession
from rental_backend.routes.rental_session import check_sessions_expiration
from rental_backend.schemas.base import StatusResponseModel
from rental_backend.schemas.models import ItemTypeAvailable, ItemTypeGet, ItemTypePost, RentStatus
from rental_backend.settings import Settings, get_settings
from rental_backend.utils.action import ActionLogger


settings: Settings = get_settings()
item_type = APIRouter(prefix="/itemtype", tags=["ItemType"])


def _calculate_cool_down_end_ts_for_types(
    item_type_ids: list[int], user_id: int | None
) -> dict[int, datetime.datetime]:
    """Return cooldown end timestamps for given item types and user based on rate limiter logic."""

    if not user_id or not item_type_ids:
        return {}

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    limiter_delta = datetime.timedelta(minutes=settings.RENTAL_SESSION_CREATE_TIME_LIMITER_MINUTES)
    cutoff_time = now - limiter_delta

    rate_limit_sessions = (
        db.session.query(RentalSession.item_type_id, RentalSession.reservation_ts)
        .filter(
            RentalSession.user_id == user_id,
            RentalSession.item_type_id.in_(item_type_ids),
            RentalSession.status.in_([RentStatus.EXPIRED, RentStatus.CANCELED]),
            RentalSession.reservation_ts > cutoff_time,
        )
        .order_by(RentalSession.item_type_id, RentalSession.reservation_ts)
        .all()
    )

    counts: dict[int, int] = defaultdict(int)
    first_reservation_ts: dict[int, datetime.datetime] = {}
    cool_down_map: dict[int, datetime.datetime] = {}

    for item_type_id, reservation_ts in rate_limit_sessions:
        counts[item_type_id] += 1
        if item_type_id not in first_reservation_ts:
            first_reservation_ts[item_type_id] = reservation_ts

        if counts[item_type_id] == settings.RENTAL_SESSION_CREATE_NUMBER_LIMITER:
            ts = first_reservation_ts[item_type_id]
            ts = ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)
            cool_down_map[item_type_id] = ts + limiter_delta

    return cool_down_map


@item_type.get("/{id}", response_model=ItemTypeGet, dependencies=[Depends(check_sessions_expiration)])
async def get_item_type(id: int, user=Depends(UnionAuth())) -> ItemTypeGet:
    """
    Retrieves information about an item type by its ID.

    - **id**: The ID of the item type.

    Returns the item type information.

    Raises **ObjectNotFound** if the item type with the specified ID is not found.
    """

    item_type: ItemType = ItemType.query(session=db.session).filter(ItemType.id == id).one_or_none()
    if item_type is None:
        raise ObjectNotFound(ItemType, id)
    result: ItemTypeGet = ItemTypeGet.model_validate(item_type)
    result.availability = ItemType.get_availability(db.session, item_type, user.get("id"))
    cool_down_map = _calculate_cool_down_end_ts_for_types([id], user.get("id"))
    result.cool_down_end_ts = cool_down_map.get(id)
    return result


@item_type.get("", response_model=list[ItemTypeGet], dependencies=[Depends(check_sessions_expiration)])
async def get_items_types(user=Depends(UnionAuth(auto_error=False))) -> list[ItemTypeGet]:
    """
    Retrieves a list of all item types.

    Returns a list of all item types.

    Raises **ObjectNotFound** if no item types are found.
    """
    item_types_all: list[ItemType] = ItemType.query(session=db.session).all()
    if not item_types_all:
        raise ObjectNotFound(ItemType, 'all')
    item_type_data_map: dict[int, tuple[bool, int]] = ItemType.get_availability_and_count_batch(
        db.session, item_types_all, user.get("id") if user else None
    )
    cool_down_map = _calculate_cool_down_end_ts_for_types(
        [item_type.id for item_type in item_types_all], user.get("id") if user else None
    )

    result: list[ItemTypeGet] = []
    for item_type in item_types_all:
        item_type: ItemType
        item_type_data = item_type_data_map.get(item_type.id, [False, 0])
        result.append(
            ItemTypeGet(
                id=item_type.id,
                name=item_type.name,
                image_url=item_type.image_url,
                description=item_type.description,
                available_items_count=item_type_data[1],
                availability=item_type_data[0],
                cool_down_end_ts=cool_down_map.get(item_type.id),
            )
        )
    return result


@item_type.post("", response_model=ItemTypeGet)
async def create_item_type(
    item_type_info: ItemTypePost,
    user=Depends(UnionAuth(scopes=["rental.item_type.create"], allow_none=False)),
) -> ItemTypeGet:
    """
    Creates a new item type.

    Scopes: `["rental.item_type.create"]`

    - **item_type_info**: The data for the new item type.

    Returns the created item type.
    """
    new_item_type = ItemType.create(session=db.session, **item_type_info.model_dump())
    ActionLogger.log_event(
        user_id=None,
        admin_id=user.get('id'),
        session_id=None,
        action_type="CREATE_ITEM_TYPE",
        details=item_type_info.model_dump(),
    )
    return ItemTypeGet.model_validate(new_item_type)


@item_type.patch("/{id}", response_model=ItemTypeGet)
async def update_item_type(
    id: int, item_type_info: ItemTypePost, user=Depends(UnionAuth(scopes=["rental.item_type.update"], allow_none=False))
) -> ItemTypeGet:
    """
    Updates the information of an item type by its ID.

    Scopes: `["rental.item_type.update"]`

    - **id**: The ID of the item type.
    - **item_type_info**: The data to update the item type with.

    Returns the updated item type.

    Raises **ObjectNotFound** if the item type with the specified ID is not found.
    """
    item_type_to_update = ItemType.get(id, session=db.session)
    if item_type_to_update is None:
        raise ObjectNotFound(ItemType, id)
    updated_item = ItemType.update(id, session=db.session, **item_type_info.model_dump())
    ActionLogger.log_event(
        user_id=None,
        admin_id=user.get('id'),
        session_id=None,
        action_type="UPDATE_ITEM_TYPE",
        details=item_type_info.model_dump(),
    )
    return ItemTypeGet.model_validate(updated_item)


@item_type.patch("/available/{id}", response_model=ItemTypeAvailable)
async def make_item_type_available(
    id: int, count: int, user=Depends(UnionAuth(scopes=["rental.item_type.update"], allow_none=False))
) -> ItemTypeAvailable:
    """
    Делает один предмет доступным по ID типа предмета.

    Скоупы: `["rental.item_type.update"]`

    - **id**: ID типа предмета.
    - **count**: Абсолютное количество предметов, которые нужно сделать доступными.
    Если доступных меньше, делает больше доступных. Если доступных больше, делает меньше доступных.
    Если нет возможности сделать count доступных, делает доступным максимально возможное количество.
    Возвращает id всех возвращенных предметов и их количество.



    Вызывает **ObjectNotFound**, если тип предмета с указанным ID не найден.
    """
    if count < 0:
        raise ValueError(count)
    types = ItemType.query(session=db.session).filter(ItemType.id == id).one_or_none()
    if not types:
        raise ObjectNotFound(ItemType, id)
    items = (
        Item.query(session=db.session)
        .outerjoin(
            RentalSession,
            and_(RentalSession.item_id == Item.id, RentalSession.status.in_([RentStatus.ACTIVE, RentStatus.RESERVED])),
        )
        .filter(Item.type_id == id, RentalSession.id.is_(None))
        .options(load_only(Item.id))
    )
    available_items = items.filter(Item.is_available == True).all()
    unavailable_items = items.filter(Item.is_available == False).all()
    result = {"item_ids": [], "items_changed": 0, "total_available": len(available_items)}
    if len(available_items) >= count:
        for item in available_items[count:]:
            updated_item = Item.update(item.id, session=db.session, is_available=False)
            result["item_ids"].append(item.id)
            result["items_changed"] += 1
            result["total_available"] -= 1
            ActionLogger.log_event(
                user_id=None,
                admin_id=user.get('id'),
                session_id=None,
                action_type="AVAILABLE_ITEM_TYPE",
                details={"id": item.id},
            )
    else:
        for item in unavailable_items[: count - len(available_items)]:
            updated_item = Item.update(item.id, session=db.session, is_available=True)
            result["item_ids"].append(item.id)
            result["items_changed"] += 1
            result["total_available"] += 1

            ActionLogger.log_event(
                user_id=None,
                admin_id=user.get('id'),
                session_id=None,
                action_type="AVAILABLE_ITEM_TYPE",
                details={"id": item.id},
            )
    return ItemTypeAvailable.model_validate(result)


@item_type.delete("/{id}", response_model=StatusResponseModel)
async def delete_item_type(
    id: int, user=Depends(UnionAuth(scopes=["rental.item_type.delete"], allow_none=False))
) -> StatusResponseModel:
    """
    Deletes an item type by its ID.

    Scopes: `["rental.item_type.delete"]`

    - **id**: The ID of the item type.

    Returns a status response.

    Raises **ObjectNotFound** if the item type with the specified ID is not found.

    Raises **ForbiddenAction** if the item type with the specified ID has items.
    """
    item_type_to_delete = ItemType.get(id, session=db.session)
    if item_type_to_delete is None:
        raise ObjectNotFound(ItemType, id)
    if len(item_type_to_delete.items) > 0:
        raise ForbiddenAction(ItemType)
    ItemType.delete(id, session=db.session)
    ActionLogger.log_event(
        user_id=None,
        admin_id=user.get('id'),
        session_id=None,
        action_type="DELETE_ITEM_TYPE",
        details={"id": id},
    )
    return StatusResponseModel(
        status="success", message="ItemType deleted successfully", ru="Тип предмета успешно удален"
    )
