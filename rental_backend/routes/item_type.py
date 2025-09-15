from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends
from fastapi_sqlalchemy import db

from rental_backend.exceptions import ObjectNotFound
from rental_backend.models.db import Item, ItemType, RentalSession
from rental_backend.schemas.base import StatusResponseModel
from rental_backend.schemas.models import ItemGet, ItemTypeGet, ItemTypePost
from rental_backend.settings import Settings, get_settings
from rental_backend.utils.action import ActionLogger


settings: Settings = get_settings()
item_type = APIRouter(prefix="/itemtype", tags=["ItemType"])


@item_type.get("/{id}", response_model=ItemTypeGet)
async def get_item_type(id: int) -> ItemTypeGet:
    """
    Retrieves information about an item type by its ID.

    - **id**: The ID of the item type.

    Returns the item type information.

    Raises **ObjectNotFound** if the item type with the specified ID is not found.
    """
    item_type: ItemType = ItemType.query(session=db.session).filter(ItemType.id == id).one_or_none()
    if item_type is None:
        raise ObjectNotFound(ItemType, id)
    free_items_count: int = Item.query(session=db.session).filter(Item.type_id == id, Item.is_available == True).count()
    item_type.free_items_count = free_items_count
    return ItemTypeGet.model_validate(item_type)


@item_type.get("", response_model=list[ItemTypeGet])
async def get_items_types() -> list[ItemTypeGet]:
    """
    Retrieves a list of all item types.

    Returns a list of all item types.

    Raises **ObjectNotFound** if no item types are found.
    """
    item_types_all: list[ItemType] = ItemType.query(session=db.session).all()
    if not item_types_all:
        raise ObjectNotFound(ItemType, 'all')
    for item_type in item_types_all:
        item_type.free_items_count = (
            Item.query(session=db.session).filter(Item.type_id == item_type.id, Item.is_available == True).count()
        )
    return [ItemTypeGet.model_validate(item_type) for item_type in item_types_all]


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


@item_type.patch("/available/{id}", response_model=ItemGet)
async def update_item_type(
    id: int, user=Depends(UnionAuth(scopes=["rental.item_type.update"], allow_none=False))
) -> ItemGet:
    """
    Makes one item available of an item_type by its ID.

    Scopes: `["rental.item_type.update"]`

    - **id**: The ID of the item type.

    Returns the updated availability of item of an item_type.

    Raises **ObjectNotFound** if the available item type with the specified ID is not found.
    """
    item = Item.query(session=db.session).filter(Item.type_id == id, Item.is_available == False).first()
    if not item:
        raise ObjectNotFound(ItemType, id)
    session: RentalSession = (
        RentalSession.query(session=db.session)
        .filter(RentalSession.item_id == item.id, RentalSession.status != "active")
        .one_or_none()
    )
    if session:
        updated_item = Item.update(item.id, session=db.session, is_available=True)
        ActionLogger.log_event(
            user_id=None,
            admin_id=user.get('id'),
            session_id=None,
            action_type="AVAILABLE_ITEM_TYPE",
            details={"id": id},
        )
        return ItemGet.model_validate(updated_item)
    if not session:
        raise ForbiddenAction(ItemType)


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
    """
    item_type_to_delete = ItemType.get(id, session=db.session)
    if item_type_to_delete is None:
        raise ObjectNotFound(ItemType, id)
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
