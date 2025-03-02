import datetime
import re
from typing import Literal

import aiohttp
from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend import settings
from rental_backend.exceptions import ObjectNotFound
from rental_backend.models.db import Item
from rental_backend.schemas.models import ItemGet, ItemPost
from rental_backend.utils.action import ActionLogger
from rental_backend.settings import get_settings, Settings

settings: Settings = get_settings()
item = APIRouter(prefix="/item", tags=["Item"])


@item.get("/item", response_model=list[ItemGet])
async def get_items(user=Depends(UnionAuth(scopes=["rental.item.read"]))) -> list[Item]:
    items = Item.query(session=db.session).all()
    return [ItemGet.model_validate(item) for item in items]


@item.post("/item", response_model=ItemGet)
async def create_item(item: ItemPost, user=Depends(UnionAuth(scopes=["rental.item.create"]))) -> ItemGet:
    new_item = Item.create(session=db.session, **item.model_dump())
    ActionLogger.log_event(
        user_id=None, admin_id=user.id, session_id=None, action_type="CREATE_ITEM", details=ItemGet.model_validate(new_item).model_dump()
    )
    return ItemGet.model_validate(new_item)


@item.patch("/item/{id}", response_model=ItemGet)
async def update_item(id: int, is_available: bool, user=Depends(UnionAuth(scopes=["rental.item.update"]))) -> ItemGet:
    item = Item.query(session=db.session).filter(Item.id == id).one_or_none()
    if item:
        item.is_available = is_available
        ActionLogger.log_event(
            user_id=None, admin_id=user.id, session_id=None, action_type="UPDATE_ITEM", details=ItemGet.model_validate(item).model_dump()
        )
        return ItemGet.model_validate(item)
    raise ObjectNotFound(Item, id)
