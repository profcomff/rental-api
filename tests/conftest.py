import importlib
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import pytest
from _pytest.monkeypatch import MonkeyPatch
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from rental_backend.models.db import *
from rental_backend.routes import app
from rental_backend.settings import Settings, get_settings


class PostgresConfig:
    """Дата-класс со значениями для контейнера с тестовой БД и alembic-миграции."""

    container_name: str = 'rental_test'
    username: str = 'postgres'
    host: str = 'localhost'
    image: str = 'postgres:15'
    external_port: int = 5433
    ham: str = 'trust'
    alembic_ini: str = Path(__file__).resolve().parent.parent / 'alembic.ini'

    @classmethod
    def get_url(cls):
        """Возвращает URI для подключения к БД."""
        return f'postgresql://{cls.username}@{cls.host}:{cls.external_port}/postgres'


@pytest.fixture(scope="session")
def session_mp():
    """Аналог monkeypatch, но с session-scope."""
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope='session')
def get_settings_mock(session_mp):
    """Переопределение get_settings в rental_backend/settings.py и перезагрузка base.app."""

    @lru_cache
    def get_test_settings() -> Settings:
        settings = Settings()
        settings.DB_DSN = PostgresConfig.get_url()
        return settings

    get_settings.cache_clear()
    dsn_mock = session_mp.setattr('rental_backend.settings.get_settings', get_test_settings)
    reloaded_module = sys.modules['rental_backend.routes.base']
    importlib.reload(reloaded_module)
    importlib.reload(sys.modules['rental_backend.routes.exc_handlers'])
    globals()['app'] = reloaded_module.app
    return dsn_mock


@pytest.fixture(scope="session")
def db_container(get_settings_mock):
    container = PostgresContainer(image=PostgresConfig.image, port=PostgresConfig.external_port, dbname=PostgresConfig.container_name) \
        .with_env("POSTGRES_HOST_AUTH_METHOD", PostgresConfig.ham)
    container.start()
    cfg = AlembicConfig(str(PostgresConfig.alembic_ini.resolve()))
    command.upgrade(cfg, "head")
    try:
        yield PostgresConfig.get_url()
    finally:
        container.stop()


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


@pytest.fixture
def base_rentses_url(request, base_test_url: str) -> str:
    """Формирует корневой URL для объекта.

    URL определяется по переменной obj_prefix в файле теста,
    в котором вызывается данная фикстура.
    """
    prefix = getattr(request.module, 'obj_prefix', None)
    if prefix is None:
        raise AttributeError('Для работы данной фикстуры требуется определить obj_prefix в файле, содержащем тест!')
    return f'{base_test_url}{prefix}'


@pytest.fixture()
def dbsession(db_container):
    """Фикстура настройки Session для работы с БД в тестах.

    .. caution::
        Очистка производится путем удаления ВСЕХ объектов Event, Item,
        ItemType и RentalSession из БД после тестов => Не запускайте эту фикстуру на
        БД с данными, которые создаете вне тестов!
    """
    engine = create_engine(str(db_container), pool_pre_ping=True)
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
    item_types = [
        ItemType(name="Type1"),
        ItemType(name="Type2"),
    ]
    for item_type in item_types:
        dbsession.add(item_type)
    dbsession.commit()
    return item_types


@pytest.fixture
def item_types(dbsession) -> List[ItemType]:
    """Создает 2 itemType в БД и возвращает их."""
    itemtypes = []
    for ind in range(2):
        itemtypes.append(ItemType.create(session=dbsession, name=f'Test ItemType {ind}'))
    dbsession.commit()
    return itemtypes


@pytest.fixture()
def item_fixture(dbsession, item_type_fixture):
    """Фикстура Item.

    .. note::
        Очистка производится в dbsession.
    """
    item = Item(type_id=item_type_fixture[0].id)
    dbsession.add(item)
    dbsession.commit()
    return item


@pytest.fixture()
def items_with_types(dbsession):
    """Фикстура Item.

    .. note::
        Фикстура создает три item: последний с флагом is_available=False
    """
    item_types = [
        ItemType(name="Type1"),
        ItemType(name="Type2"),
        ItemType(name="Type3"),
    ]
    for item_type in item_types:
        dbsession.add(item_type)
    dbsession.commit()

    items = [
        Item(type_id=item_types[0].id, is_available=True),
        Item(type_id=item_types[1].id, is_available=True),
        Item(type_id=item_types[2].id, is_available=False),
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


@pytest.fixture
def items_with_same_type(dbsession, item_types) -> List[Item]:
    """Создает 2 Item с одним itemType в БД и возвращает их."""
    items = []
    for _ in range(2):
        items.append(Item.create(session=dbsession, type_id=item_types[0].id))
    dbsession.commit()
    return items


@pytest.fixture()
def expire_mock(mocker):
    """Mock-объект для функции check_session_expiration."""
    fake_check = mocker.patch('rental_backend.routes.rental_session.check_session_expiration')
    fake_check.return_value = True
    return fake_check


@pytest.fixture
def expiration_time_mock(mocker):
    """Мок для RENTAL_SESSION_EXPIRY, чтобы не ждать в ходе тестов."""
    fast_expiration = mocker.patch(
        'rental_backend.routes.rental_session.RENTAL_SESSION_EXPIRY', new=datetime.timedelta(seconds=2)
    )
    return fast_expiration


@pytest.fixture
def rentses(dbsession, item_fixture, authlib_user) -> RentalSession:
    """Экземпляр RentalSession, создаваемый в POST /rental_session.

    .. note::
        Очистка происходит в dbsession.
    """
    rent = RentalSession.create(
        session=dbsession,
        user_id=authlib_user.get("id"),
        item_id=item_fixture.id,
        status=RentStatus.RESERVED,
    )
    item_fixture.is_available = False
    dbsession.add(rent, item_fixture)
    dbsession.commit()
    return rent


@pytest.fixture
def another_rentses(dbsession, items_with_same_type, another_authlib_user) -> RentalSession:
    """Еще один экземпляр RentalSession с отличающимся пользователем."""
    renting_item = items_with_same_type[0]
    rent = RentalSession.create(
        session=dbsession,
        user_id=another_authlib_user.get("id"),
        item_id=renting_item.id,
        status=RentStatus.RESERVED,
    )
    Item.update(id=renting_item.id, session=dbsession, is_available=False)
    dbsession.add(rent)
    dbsession.commit()
    return rent


@pytest.fixture
def active_rentses(dbsession, item_fixture, authlib_user) -> RentalSession:
    """Начатая сессия аренды."""
    rent = RentalSession.create(
        session=dbsession,
        user_id=authlib_user.get("id"),
        item_id=item_fixture.id,
        status=RentStatus.ACTIVE,
    )
    item_fixture.is_available = False
    dbsession.add(rent, item_fixture)
    dbsession.commit()
    return rent


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
