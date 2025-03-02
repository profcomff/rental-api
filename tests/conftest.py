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


@pytest.fixture()
def item_type_fixture(dbsession):
    item_type = ItemType(id=0, name='Test ItemType')
    dbsession.add(item_type)
    dbsession.commit()
    yield item_type
    dbsession.refresh(item_type)
    dbsession.delete(item_type)
    dbsession.commit()


@pytest.fixture(scope="function")
def item_fixture(dbsession, item_type_fixture):
    item = Item(type_id=item_type_fixture.id)
    dbsession.add(item)
    dbsession.commit()
    yield item
    dbsession.delete(item)
    dbsession.commit()


@pytest.fixture(scope="function")
def items_with_types(dbsession):
    item_types = [
        ItemType(name="Type1"),
        ItemType(name="Type2"),
    ]
    dbsession.add_all(item_types)
    dbsession.commit()

    items = [
        Item(type_id=item_types[0].id),
        Item(type_id=item_types[1].id),
    ]
    dbsession.add_all(items)
    dbsession.commit()

    yield items, item_types

    for item in items:
        dbsession.delete(item)
    for item_type in item_types:
        dbsession.delete(item_type)
    dbsession.commit()
