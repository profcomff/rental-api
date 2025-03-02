from fastapi_sqlalchemy import db

from rental_backend.models.db import Event


class ActionLogger:
    @classmethod
    def log_event(
        cls, user_id: int | None, admin_id: int | None, session_id: int | None, action_type: str, details: dict
    ):
        event = Event(
            user_id=user_id, admin_id=admin_id, session_id=session_id, action_type=action_type, details=details
        )
        db.session.add(event)
        db.session.commit()
