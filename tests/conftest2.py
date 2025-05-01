import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from rental_backend.models.db import *
from rental_backend.routes import app
from rental_backend.settings import Settings, get_settings


@pytest.fixture
def client(mocker, authlib_user):
    user_mock = mocker.patch('auth_lib.fastapi.UnionAuth.__call__')
    user_mock.return_value = authlib_user
    client = TestClient(app)
    return client


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


@pytest.fixture
def item_fixture(dbsession):
    items = [
        Item(type_id=1, is_available=True),
        Item(type_id=2, is_available=False),
        Item(type_id=None, is_available=True)
    ]
    dbsession.add_all(items)
    dbsession.commit()
    return items

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
