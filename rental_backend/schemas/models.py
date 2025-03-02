import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator
from typing import Optional
from rental_backend.schemas.base import Base
from rental_backend.models.db import RentalSession, RentStatus

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




class RentalSessionBase(Base):
    item_type_id: int
    reservation_ts: datetime.datetime

class RentalSessionCreate(RentalSessionBase):
    pass

class RentalSessionResponse(Base):
    id: int
    user_id: int
    item_id: int
    admin_open_id: Optional[int]
    admin_close_id: Optional[int]
    reservation_ts: datetime.datetime
    start_ts: Optional[datetime.datetime]
    end_ts: Optional[datetime.datetime]
    actual_return_ts: Optional[datetime.datetime]
    status: RentStatus
