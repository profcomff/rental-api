import datetime
from typing import Literal

import aiohttp
from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend.exceptions import AlreadyExists, ForbiddenAction, ObjectNotFound
from rental_backend.models.db import ItemType
from rental_backend.schemas.models import ItemTypeGet, ItemTypeGetAll, ItemTypePost
from rental_backend.settings import Settings, get_settings
from rental_backend.utils.action import ActionLogger


settings: Settings = get_settings()
item_type = APIRouter(prefix="/itemtype", tags=["ItemType"])


@item_type.get("/{id}", response_model=ItemTypeGet)
async def get_item_type(id: int) -> ItemTypeGet:
    item_type: ItemType = ItemType.query(session=db.session).filter(ItemType.id == id).one_or_none()
    if item_type is None:
        raise ObjectNotFound(ItemType, id)
    return ItemTypeGet.model_validate(item_type)


@item_type.get("", response_model=ItemTypeGetAll)
async def get_items_types() -> ItemTypeGetAll:
    item_types_all = ItemType.query(session=db.session).all()
    if not item_types_all:
        raise ObjectNotFound(ItemType, 'all')
    return ItemTypeGetAll(item_types=[ItemTypeGet.model_validate(item_type) for item_type in item_types_all])


@item_type.post("", response_model=ItemTypeGet)
async def create_item_type(
    item_type_info: ItemTypePost,
    user=Depends(UnionAuth(scopes=["rental.item_type.create"], allow_none=False)),
) -> ItemTypeGet:
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
    ItemType.get(id, session=db.session)
    if item_type is None:
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
