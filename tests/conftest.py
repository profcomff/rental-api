from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rental_backend.models.db import *
from rental_backend.routes import app
from rental_backend.settings import get_settings


@pytest.fixture
def authlib_user():
    """Данные о пользователе, возвращаемые сервисом auth.

    Составлено на основе: https://clck.ru/3LWzxt
    """
    return {
        "auth_methods": ["string"],
        "session_scopes": [{"id": 0, "name": "string"}],
        "user_scopes": [{"id": 0, "name": "string"}],
        "indirect_groups": [0],
        "groups": [0],
        "id": 0,
        "email": "string",
    }


@pytest.fixture
def client(mocker, authlib_user):
    user_mock = mocker.patch('auth_lib.fastapi.UnionAuth.__call__')
    user_mock.return_value = authlib_user
    client = TestClient(app)
    return client


@pytest.fixture
def base_test_url(client):
    return client.base_url


@pytest.fixture
def dbsession():
    settings = get_settings()
    engine = create_engine(str(settings.DB_DSN), pool_pre_ping=True)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    yield session


@pytest.fixture()
def item_type_fixture(dbsession):
    """Фикстура ItemType.

    .. note::
        Очистка производится в dbsession.
    """
    item_type = ItemType(id=228322, name='Test ItemType')
    dbsession.add(item_type)
    dbsession.commit()
    yield item_type
    if item_type.items:
        for item in item_type.items:
            dbsession.delete(item)
        dbsession.flush()
    dbsession.delete(item_type)
    dbsession.commit()


@pytest.fixture(scope="function")
def item_fixture(dbsession, item_type_fixture):
    """Фикстура Item.

    .. note::
        Очистка производится в dbsession.
    """
    item = Item(type_id=item_type_fixture.id)
    dbsession.add(item)
    dbsession.commit()
    return item


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
