from __future__ import annotations

import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    and_,
    case,
    exists,
    func,
    not_,
    select,
    text,
)
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
    type: Mapped[ItemType] = relationship("ItemType", back_populates="items")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sessions: Mapped[list[RentalSession]] = relationship(
        "RentalSession",
        back_populates="item",
        primaryjoin="and_(RentalSession.item_id == Item.id, not_(RentalSession.is_deleted))",
    )


class ItemType(BaseDbModel):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    items: Mapped[list[Item]] = relationship(
        "Item", back_populates="type", primaryjoin="and_(ItemType.id==Item.type_id, Item.is_deleted==False)"
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    @staticmethod
    def get_availability_and_count_batch(
        session, item_type_data: list[ItemType], user_id: int | None
    ) -> dict[int, tuple[bool, int]]:
        item_type_ids = [it.id for it in item_type_data]
        if user_id is None:
            return {item_type_id: (False, 0) for item_type_id in item_type_ids}

        available_count_subq = (
            select(Item.type_id.label("type_id"), func.count().label("available_count"))
            .where(Item.is_available == True, Item.is_deleted == False)
            .group_by(Item.type_id)
            .subquery()
        )
        stmt = (
            select(
                ItemType.id.label("item_type_id"),
                case(
                    (
                        and_(
                            exists().where(Item.type_id == ItemType.id, Item.is_available == True),
                            not_(
                                exists().where(
                                    RentalSession.user_id == user_id,
                                    RentalSession.status.in_(
                                        [
                                            RentStatus.ACTIVE,
                                            RentStatus.RESERVED,
                                            RentStatus.OVERDUE,
                                        ]
                                    ),
                                    RentalSession.item.has(Item.type_id == ItemType.id),
                                )
                            ),
                        ),
                        True,
                    ),
                    else_=False,
                ).label("is_available_for_user"),
                func.coalesce(available_count_subq.c.available_count, 0).label("available_items_count"),
            )
            .outerjoin(available_count_subq, available_count_subq.c.type_id == ItemType.id)
            .where(ItemType.id.in_(item_type_ids))
        )

        results = session.execute(stmt).all()
        result_map = {r.item_type_id: (r.is_available_for_user, r.available_items_count) for r in results}
        return result_map

    @hybrid_property
    def available_items_count(self) -> int:
        return sum(1 for item in self.items if item.is_available)


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
        server_default=text("CURRENT_DATE + interval '18 hours'"),
    )
    user_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    user_fullname: Mapped[str | None] = mapped_column(String, nullable=True)
    strike = relationship("Strike", uselist=False, back_populates="session")
    item: Mapped[Item] = relationship(
        "Item", back_populates="sessions", primaryjoin="and_(RentalSession.item_id == Item.id, not_(Item.is_deleted))"
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Strike(BaseDbModel):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("rental_session.id"), nullable=True)
    admin_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String)
    create_ts: Mapped[datetime.datetime] = mapped_column(DateTime)
    session = relationship("RentalSession", back_populates="strike")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
