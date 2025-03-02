from __future__ import annotations

import datetime
import logging
import uuid
from enum import Enum

from fastapi_sqlalchemy import db
from sqlalchemy import JSON, UUID, Boolean, DateTime
from sqlalchemy import Enum as DbEnum
from sqlalchemy import ForeignKey, Integer, String, UnaryExpression, and_, func, nulls_last, or_, true
from sqlalchemy.ext.hybrid import hybrid_method, hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm.attributes import InstrumentedAttribute

from .base import BaseDbModel


class RentStatus(str, Enum):
    RESERVED: str = "reserved"
    ACTIVE: str = "active"
    CANCELED: str = "canceled"
    DISMISSED: str = "dismissed"


class Item(BaseDbModel):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type_id: Mapped[int] = mapped_column(Integer, ForeignKey("item_type.id"))
    is_available: Mapped[bool] = mapped_column(Boolean, default=False)
    type: Mapped["ItemType"] = relationship("ItemType", back_populates="items")


class ItemType(BaseDbModel):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    items: Mapped[list[Item]] = relationship("Item", back_populates="type")


class RentalSession(BaseDbModel):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("item.id"))
    admin_open_id: Mapped[int] = mapped_column(Integer)
    admin_close_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reservation_ts: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    start_ts: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    end_ts: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    actual_return_ts: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    status: Mapped[RentStatus] = mapped_column(String, nullable=False)


class Event(BaseDbModel):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=True)
    admin_id: Mapped[int] = mapped_column(Integer, nullable=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("rental_session.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=True)
    create_ts: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class Strike(BaseDbModel):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("rental_session.id"), nullable=True)
    admin_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String)
    create_ts: Mapped[datetime.datetime] = mapped_column(DateTime)
