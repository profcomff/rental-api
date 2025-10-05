import datetime
from typing import Optional

from auth_lib.fastapi import UnionAuth
from fastapi import APIRouter, Depends, Query
from fastapi_sqlalchemy import db

from rental_backend.exceptions import DateRangeError, ObjectNotFound
from rental_backend.models.db import RentalSession, Strike
from rental_backend.schemas.base import StatusResponseModel
from rental_backend.schemas.models import StrikeGet, StrikePost
from rental_backend.utils.action import ActionLogger


strike = APIRouter(prefix="/strike", tags=["Strike"])


@strike.post("", response_model=StrikeGet)
async def create_strike(
    strike_info: StrikePost, user=Depends(UnionAuth(scopes=["rental.strike.create"], allow_none=False))
) -> StrikeGet:
    """
    Creates a new strike.

    Scopes: `["rental.strike.create"]`

    - **strike_info**: The data for the new strike.

    Returns the created strike.

    If session does not exist returns ObjectNotFound.
    """
    sessions = db.session.query(RentalSession).filter(RentalSession.id == strike_info.session_id).one_or_none()
    print(sessions)
    if not sessions:
        raise ObjectNotFound(RentalSession, strike_info.session_id)
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
    """
    Retrieves a list of strikes for a specific user.

    - **user_id**: The ID of the user.

    Returns a list of strikes.
    """
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
    """
    Retrieves a list of strikes with optional filtering.

    Scopes: `["rental.strike.read"]`

    - **admin_id**: Filter strikes by admin ID.
    - **session_id**: Filter strikes by session ID.
    - **from_date**: Filter strikes created after this date.
    - **to_date**: Filter strikes created before this date.

    Returns a list of strikes.

    Raises **DateRangeError** if only one of `from_date` or `to_date` is provided.
    """
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
        query = query.filter(Strike.create_ts.between(from_date, to_date))
    strikes = query.all()
    return [StrikeGet.model_validate(strike) for strike in strikes]


@strike.delete("/{id}")
async def delete_strike(id: int, user=Depends(UnionAuth(scopes=["rental.strike.delete"], allow_none=False))) -> dict:
    """
    Deletes a strike by its ID.

    Scopes: `["rental.strike.delete"]`

    - **id**: The ID of the strike to delete.

    Returns a status response.

    Raises **ObjectNotFound** if the strike with the specified ID is not found.
    """
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
