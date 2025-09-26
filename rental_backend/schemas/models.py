import datetime
from typing import Optional

from pydantic import field_validator

from rental_backend.models.db import RentStatus
from rental_backend.schemas.base import Base


class ItemTypeGet(Base):
    id: int
    name: str
    image_url: str | None = None
    description: str | None = None
    free_items_count: int | None = None
    availability: bool = False


class ItemTypePost(Base):
    name: str
    image_url: str | None = None
    description: str | None = None


class ItemTypeAvailable(Base):
    item_ids: list[int]
    items_changed: int
    total_available: int


class ItemGet(Base):
    id: int
    type_id: int
    is_available: bool = False


class ItemPost(Base):
    type_id: int
    is_available: bool = False


class EventGet(Base):
    id: int
    user_id: int | None = None
    admin_id: int | None = None
    session_id: int | None = None
    action_type: str
    details: dict
    create_ts: datetime.datetime


class StrikePost(Base):
    user_id: int
    admin_id: int
    reason: str
    session_id: int | None = None


class StrikeGet(Base):
    id: int
    user_id: int
    admin_id: int
    reason: str
    session_id: int | None = None
    create_ts: datetime.datetime


class RentalSessionPost(Base):
    item_type_id: int
    deadline_ts: datetime.datetime | None

    @field_validator('deadline_ts')
    @classmethod
    def check_deadline_ts(cls, value):
        if value < datetime.datetime.now(tz=datetime.timezone.utc):
            raise ValueError("Время дедлайна аренды не может быть меньше, текущего времени")
        return value


class RentalSessionGet(Base):
    id: int
    user_id: int
    item_id: int
    item_type_id: int
    admin_open_id: int | None
    admin_close_id: int | None
    reservation_ts: datetime.datetime
    start_ts: datetime.datetime | None
    end_ts: datetime.datetime | None
    actual_return_ts: datetime.datetime | None
    status: RentStatus
    strike_id: int | None = None
    user_phone: str | None = None
    deadline_ts: datetime.datetime | None = None


class RentalSessionPatch(Base):
    status: Optional[RentStatus] = None
    end_ts: Optional[datetime.datetime] = None
    actual_return_ts: Optional[datetime.datetime] = None
    admin_close_id: Optional[int] = None


class RentalSessionStartPatch(Base):
    session_id: int
    deadline_ts: datetime.datetime | None

    @field_validator('deadline_ts')
    @classmethod
    def check_deadline_ts(cls, value):
        if value < datetime.datetime.now(tz=datetime.timezone.utc):
            raise ValueError("Время дедлайна аренды не может быть меньше, текущего времени")
        return value
