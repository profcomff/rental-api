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
    Retrieves a list of items. If `type_id` is specified, only items of that type are returned.

    - **type_id**: The ID of the item type (optional).

    Returns a list of items.
    """
    query = Item.query(session=db.session)
    if type_id is not None:
        query = query.filter(Item.type_id == type_id)
    items = query.all()
    return [ItemGet.model_validate(item) for item in items]


@item.post("", response_model=ItemGet)
async def create_item(item: ItemPost, user=Depends(UnionAuth(scopes=["rental.item.create"]))) -> ItemGet:
    """
    Creates a new item.

    Scopes: `["rental.item.create"]`

    - **item**: The data for the new item.

    Returns the created item.

    Raises **ObjectNotFound** if the item type with the specified `type_id` is not found.
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
    Updates the availability status of an item by its ID.

    Scopes: `["rental.item.patch"]`

    - **id**: The ID of the item.
    - **is_available**: The new availability status for the item.

    Returns the updated item.

    Raises **ObjectNotFound** if the item with the specified ID is not found.
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
    Deletes an item by its ID.

    Scopes: `["rental.item.delete"]`

    - **id**: The ID of the item.

    Returns a status response.

    Raises **ObjectNotFound** if the item with the specified ID is not found.
    """
    rental_sessions = db.session.query(RentalSession).filter(RentalSession.item_id == id)
    session = rental_sessions.filter(
        RentalSession.status.in_([RentStatus.ACTIVE, RentStatus.OVERDUE, RentStatus.RESERVED])
    ).one_or_none()
    if session is not None:
        raise ObjectNotFound(Item, id)
    Item.delete(id, session=db.session)
    for rental_session in rental_sessions:
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
    Получает предмет по его идентификатору.
    """
    item = Item.get(id=id, session=db.session)
    return ItemGet.model_validate(item)
