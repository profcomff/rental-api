import datetime
from typing import Literal

import aiohttp
from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend.exceptions import (
    ObjectNotFound,
    AlreadyExists,
    ForbiddenAction
)
from rental_backend.models.db import ItemType
from rental_backend.settings import Settings, get_settings
from rental_backend.schemas.models import ItemTypeGet, ItemTypeGetAll, ItemTypePost

settings: Settings = get_settings()
item_type = APIRouter(prefix="/item-type", tags=["Item_type"])

@item_type.get("/{id}", response_model=ItemTypeGet)
async def get_item_type(id: int) -> ItemTypeGet:
    item_type: ItemType = ItemType.query(session=db.session).filter(ItemType.id == id).one_or_none()
    if item_type is None:
        raise ObjectNotFound
    return ItemTypeGet.model_validate(item_type)

@item_type.get("", response_model=ItemTypeGetAll)
async def get_items_types() -> ItemTypeGetAll:
    item_types_all = ItemType.query(session=db.session).all()
    if not item_types_all:
        raise ObjectNotFound(ItemType, 'all')
    return ItemTypeGetAll(item_types = [ItemTypeGet.model_validate(item_type) for item_type in item_types_all])

@item_type.post("", response_model=ItemTypeGet)
async def create_item_type(item_type_info: ItemTypePost, user=Depends(UnionAuth(scopes=["rental.item_type.create"], allow_none=False, auto_error=True))) -> ItemTypeGet:
    new_item_type = ItemType.create(session=db.session, **item_type_info.model_dump())
    db.session.commit()
    return ItemTypeGet.model_validate(new_item_type)

