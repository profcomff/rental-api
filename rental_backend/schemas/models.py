import datetime


from pydantic import field_validator
from uuid import UUID

from pydantic import BaseModel


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

