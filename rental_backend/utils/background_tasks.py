import datetime

from fastapi_sqlalchemy import db

from rental_backend.models.db import RentalSession, RentStatus


def check_session_expiration():
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    expired_sessions = (
        RentalSession.query(session=db.session)
        .filter(
            RentalSession.status == RentStatus.RESERVED,
            RentalSession.reservation_ts <= now - datetime.timedelta(minutes=1),
        )
        .all()
    )

    for session in expired_sessions:
        RentalSession.update(session=db.session, id=session.id, status=RentStatus.CANCELED)
