import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

from rental_backend.schemas.base import Base


class ItemTypeGet(Base):
    id: int
    name: str
    image_url: str | None
    description: str | None


class ItemTypeGetAll(Base):
    item_types: list[ItemTypeGet]


class ItemTypePost(Base):
    name: str
    image_url: str | None
    description: str | None


class ItemGet(Base):
    id: int
    type_id: int
    is_available: bool = False


class ItemPost(Base):
    type_id: int
    is_available: bool = False


class EventGet(BaseModel):
    id: int
    user_id: int | None = None
    admin_id: int | None = None
    session_id: int | None = None
    action_type: str
    details: dict
    create_ts: datetime.datetime


# Модель для создания страйка
class StrikePost(BaseModel):
    user_id: int
    admin_id: int
    reason: str
    session_id: int | None = None


# Модель для получения страйка
class StrikeGet(BaseModel):
    id: int
    user_id: int
    admin_id: int
    reason: str
    session_id: int | None = None
    created_ts: datetime.datetime
