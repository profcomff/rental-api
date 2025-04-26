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
def another_authlib_user():
    """Данные об еще одном пользователе, возвращаемые сервисом auth.

    Составлено на основе: https://clck.ru/3LWzxt
    """
    return {
        "auth_methods": ["string"],
        "session_scopes": [{"id": 0, "name": "string"}],
        "user_scopes": [{"id": 0, "name": "string"}],
        "indirect_groups": [0],
        "groups": [0],
        "id": 1,
        "email": "string",
    }


@pytest.fixture
def authlib_mock(mocker):
    """Мок верификации AuthLib."""
    auth_mock = mocker.patch('auth_lib.fastapi.UnionAuth.__call__')
    return auth_mock


@pytest.fixture
def user_mock(authlib_mock, authlib_user):
    """Мок UnionAuth с возвращением данных для authlib_user."""
    authlib_mock.return_value = authlib_user
    return authlib_mock


@pytest.fixture
def another_user_mock(authlib_mock, another_authlib_user):
    """Мок UnionAuth с возвращением данных для another_authlib_user."""
    authlib_mock.return_value = another_authlib_user
    return authlib_mock


@pytest.fixture
def client(user_mock):
    client = TestClient(app, raise_server_exceptions=False)
    return client


@pytest.fixture
def another_client(another_user_mock):
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


def make_url_query(data: Dict) -> str:
    """Вспомогательная функция для преобразования входных данных
    в строку параметров URL.
    """
    if len(data) == 0:
        return ''
    if len(data) == 1:
        for k in data:
            return f'?{k}={data[k]}'
    return '?' + '&'.join(f'{k}={data[k]}' for k in data)
