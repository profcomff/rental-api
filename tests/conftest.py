import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from rental_backend.models.db import *
from rental_backend.routes import app
from rental_backend.settings import Settings, get_settings


@pytest.fixture
def client(mocker):
    user_mock = mocker.patch('auth_lib.fastapi.UnionAuth.__call__')
    user_mock.return_value = {
        "session_scopes": [{"id": 0, "name": "string", "comment": "string"}],
        "user_scopes": [{"id": 0, "name": "string", "comment": "string"}],
        "indirect_groups": [{"id": 0, "name": "string", "parent_id": 0}],
        "groups": [{"id": 0, "name": "string", "parent_id": 0}],
        "id": 0,
        "email": "string",
    }
    client = TestClient(app)
    return client


@pytest.fixture()
def dbsession():
    settings = get_settings()
    engine = create_engine(str(settings.DB_DSN), pool_pre_ping=True)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.query(Event).delete()
    session.commit()
    session.rollback()
    session.close()


@pytest.fixture(scope='function')
def items(dbsession):
    """
    Creates 4 lecturers(one with flag is_deleted=True)
    """
    items_data = [
        (9900, True),
        (8999, True),
        (8998, True),
    ]
    items = [
        Item(type_id=ftype, is_available=available)
        for ftype, available in items_data
    ]
    items.append(
        Item(type_id=8997, is_available=True)
    )
    items[-1].is_deleted = True
    for item in items:
        dbsession.add(item)
    dbsession.commit()
    yield items
    for item in items:
        dbsession.refresh(item)
        dbsession.delete(item)
    dbsession.commit()