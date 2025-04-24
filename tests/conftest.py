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
    # app.build_middleware_stack  # TODO: Посмотреть в сторону этих замещений. Тогда тесты и сервис будут разведены. https://github.com/fastapi/fastapi/issues/2495
    # app.user_middleware
    client = TestClient(app, raise_server_exceptions=False)
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
    session.query(Strike).delete()
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


# Utils
def model_to_dict(model: BaseDbModel) -> Dict[str, Any]:
    """Возвращает поля модели БД в виде словаря."""
    model_dict = dict()
    for col in model.__table__.columns:
        model_dict[col.name] = getattr(model, col.name)
    return model_dict
