import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

from rental_backend.schemas.base import Base


# Модель для Item
class ItemGet(Base):
    id: int
    type_id: int
    is_available: bool = False


class ItemPost(Base):
    type_id: int
    is_available: bool = False


# Pydantic модель для Event
class EventGet(BaseModel):
    id: int
    user_id: int | None = None
    admin_id: int | None = None
    session_id: int | None = None
    action_type: str
    details: dict
    create_ts: datetime.datetime
