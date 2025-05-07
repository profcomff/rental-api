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


@pytest.fixture()
def dbsession():
    """Фикстура настройки Session для работы с БД в тестах.

    .. caution::
        Очистка производится путем удаления ВСЕХ объектов Event, Item,
        ItemType и RentalSession из БД после тестов => Не запускайте эту фикстуру на
        БД с данными, которые создаете вне тестов!
    """
    settings = get_settings()
    engine = create_engine(str(settings.DB_DSN), pool_pre_ping=True)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.query(Event).delete()
    session.query(RentalSession).delete()
    session.query(Item).delete()
    session.query(ItemType).delete()
    session.commit()
    session.rollback()
    session.close()


@pytest.fixture()
def item_type_fixture(dbsession):
    """Фикстура ItemType.

    .. note::
        Очистка производится в dbsession.
    """
    item_type = ItemType(id=0, name='Test ItemType')
    dbsession.add(item_type)
    dbsession.commit()
    return item_type


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
        ItemType(id=123451, name="Type1"),
        ItemType(id=123444, name="Type2"),
        ItemType(id=990876, name="Type3"),
    ]
    for item_type in item_types:
        dbsession.add(item_type)
    dbsession.commit()

    items = [
        Item(id=1, type_id=item_types[0].id, is_available=True),
        Item(id=2, type_id=item_types[1].id, is_available=True),
        Item(id=3, type_id=item_types[2].id, is_available=False),
    ]
    for i in items:
        dbsession.add(i)
    dbsession.commit()
    yield items
    for i in item_types:
        for item in i.items:
            dbsession.delete(item)
        dbsession.flush()
        dbsession.delete(i)
    dbsession.commit()


# Utils
def model_to_dict(model: BaseDbModel) -> Dict[str, Any]:
    """Возвращает поля модели БД в виде словаря."""
    model_dict = dict()
    for col in model.__table__.columns:
        model_dict[col.name] = getattr(model, col.name)
    return model_dict
