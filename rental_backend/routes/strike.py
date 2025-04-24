import datetime
from typing import Optional

from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend.exceptions import DateRangeError
from rental_backend.models.db import Strike
from rental_backend.schemas.models import StrikeGet, StrikePost
from rental_backend.utils.action import ActionLogger


strike = APIRouter(prefix="/strike", tags=["Strike"])


@strike.post("", response_model=StrikeGet)
async def create_strike(
    strike_info: StrikePost, user=Depends(UnionAuth(scopes=["rental.strike.create"], allow_none=False))
) -> StrikeGet:
    new_strike = Strike.create(
        session=db.session, **strike_info.model_dump(), create_ts=datetime.datetime.now(tz=datetime.timezone.utc)
    )
    ActionLogger.log_event(
        user_id=strike_info.user_id,
        admin_id=user.get('id'),
        session_id=strike_info.session_id,
        action_type="CREATE_STRIKE",
        details=strike_info.model_dump(),
    )
    return StrikeGet.model_validate(new_strike)


@strike.get("/user/{user_id}", response_model=list[StrikeGet])
async def get_user_strikes(user_id: int) -> list[StrikeGet]:
    strikes = Strike.query(session=db.session).filter(Strike.user_id == user_id).all()
    return [StrikeGet.model_validate(strike) for strike in strikes]


@strike.get("", response_model=list[StrikeGet])
async def get_strikes(
    user_id: Optional[int] = Query(None),
    admin_id: Optional[int] = Query(None),
    session_id: Optional[int] = Query(None),
    from_date: Optional[datetime.datetime] = Query(None),
    to_date: Optional[datetime.datetime] = Query(None),
    user=Depends(UnionAuth(scopes=["rental.strike.read"], allow_none=False)),
) -> list[StrikeGet]:
    if (from_date is None) != (to_date is None):
        raise DateRangeError()

    query = Strike.query(session=db.session)
    if user_id is not None:
        query = query.filter(Strike.user_id == user_id)
    if admin_id is not None:
        query = query.filter(Strike.admin_id == admin_id)
    if session_id is not None:
        query = query.filter(Strike.session_id == session_id)
    if from_date is not None and to_date is not None:
        query = query.filter(Strike.created_ts.between(from_date, to_date))
    strikes = query.all()
    return [StrikeGet.model_validate(strike) for strike in strikes]


@strike.delete("/{id}")
async def delete_strike(id: int, user=Depends(UnionAuth(scopes=["rental.strike.delete"], allow_none=False))) -> dict:
    strike = Strike.get(id, session=db.session)
    if strike is None:
        raise ObjectNotFound(Strike, id)
    Strike.delete(id, session=db.session)
    ActionLogger.log_event(
        user_id=strike.user_id,
        admin_id=user.get('id'),
        session_id=None,
        action_type="DELETE_STRIKE",
    )
    return StatusResponseModel(status="success", message="Strike deleted successfully", ru="Страйк успешно удален")
