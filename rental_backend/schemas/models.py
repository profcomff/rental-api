import datetime

from pydantic import field_validator

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