from __future__ import annotations

import datetime
from enum import Enum

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func, select, text
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rental_backend.settings import Settings, get_settings

from .base import BaseDbModel


settings: Settings = get_settings()


class RentStatus(str, Enum):
    RESERVED: str = "reserved"
    ACTIVE: str = "active"
    CANCELED: str = "canceled"
    OVERDUE: str = "overdue"
    RETURNED: str = "returned"
    DISMISSED: str = "dismissed"
    EXPIRED: str = "expired"


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

    @classmethod
    def get_availability(cls, session, item_type_id: int, user_id: int) -> bool:

        available_items_count = (
            session.query(Item).filter(Item.type_id == item_type_id, Item.is_available == True).count()
        )

        if available_items_count == 0:
            return False
        user_active_rentals = (
            session.query(RentalSession)
            .join(Item, RentalSession.item_id == Item.id)
            .filter(
                RentalSession.user_id == user_id,
                Item.type_id == item_type_id,
                RentalSession.status.in_([RentStatus.ACTIVE, RentStatus.RESERVED, RentStatus.OVERDUE]),
            )
            .count()
        )
        return user_active_rentals == 0

    @hybrid_property
    def available_items_count(self) -> int:
        return sum(1 for item in self.items if item.is_available)

    @available_items_count.expression
    def available_items_count(cls):
        return select(func.count(Item.id)).where(Item.type_id == cls.id, Item.is_available == True).scalar_subquery()


class RentalSession(BaseDbModel):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("item.id"))
    admin_open_id: Mapped[int] = mapped_column(Integer, nullable=True)
    admin_close_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reservation_ts: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    start_ts: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    end_ts: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    actual_return_ts: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    status: Mapped[RentStatus] = mapped_column(String, nullable=False)
    deadline_ts: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.datetime(
            datetime.datetime.now().year,
            datetime.datetime.now().month,
            datetime.datetime.now().day,
            settings.BASE_OVERDUE,
            0,
            0,
        ),
        server_default=text("CURRENT_DATE + interval '13 hours'"),
    )
    user_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    strike = relationship("Strike", uselist=False, back_populates="session")

    strike = relationship("Strike", uselist=False, back_populates="session")
    item: Mapped["Item"] = relationship("Item")

    @hybrid_property
    def item_type_id(self) -> int | None:
        return self.item.type_id if self.item else None

    @item_type_id.expression
    def item_type_id(cls):
        return select(Item.type_id).where(Item.id == cls.item_id).scalar_subquery()


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
    session = relationship("RentalSession", back_populates="strike")
