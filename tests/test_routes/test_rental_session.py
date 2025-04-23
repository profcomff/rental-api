from typing import Tuple, List, Generator
import datetime

import pytest
from starlette import status
from sqlalchemy.exc import StatementError, DataError
from sqlalchemy import desc

from rental_backend.models.base import BaseDbModel
from rental_backend.models.db import Item, RentalSession, ItemType, Event
from rental_backend.routes.rental_session import rental_session
from rental_backend.schemas.models import RentStatus
from conftest import model_to_dict
# TODO: подумать над багом при teardown test: при ошибке в teardown (точно, если sqlalchemy), у меня не затираются тестовые объекты => некритично, но желательно починить!

# New fixtures
@pytest.fixture()
def expire_mock(mocker):
    """Mock-объект для функции check_session_expiration."""
    fake_check = mocker.patch('rental_backend.routes.rental_session.check_session_expiration')
    fake_check.return_value = True
    return fake_check


@pytest.fixture
def expiration_time_mock(mocker):
    """Мок для RENTAL_SESSION_EXPIRY, чтобы не ждать в ходе тестов."""
    fast_expiration = mocker.patch('rental_backend.routes.rental_session.RENTAL_SESSION_EXPIRY', new=datetime.timedelta(seconds=2))
    return fast_expiration


@pytest.fixture
def item_types(dbsession) -> List[ItemType]:
    """Создает 2 itemType в БД и возвращает их."""
    itemtypes = []
    for ind in range(2):
        itemtypes.append(
            ItemType.create(session=dbsession, name=f'Test ItemType {ind}')
        )
    dbsession.commit()
    return itemtypes


@pytest.fixture
def items_with_same_type(dbsession, item_types) -> List[Item]:
    """Создает 2 Item с одним itemType в БД и возвращает их."""
    items = []
    for _ in range(2):
        items.append(
            Item.create(session=dbsession, type_id=item_types[0].id)
        )
    dbsession.commit()
    return items


@pytest.fixture
def items_with_diff_types(dbsession, item_types) -> List[Item]:
    """Создает 2 Item с разными itemType в БД и возвращает их."""
    items = []
    for ind in range(2):
        items.append(
            Item.create(session=dbsession, type_id=item_types[ind].id)
        )
    dbsession.commit()
    return items


@pytest.fixture
def base_rentses_url(base_test_url: str) -> str:
    """Формирует корневой URL для Item."""
    return f'{base_test_url}{rental_session.prefix}'


@pytest.fixture
def available_item(dbsession, item_fixture):
    """Item, доступный для аренды.

    .. note::
        Очистка производится в dbsession.
    """
    if item_fixture.is_available == False:
        Item.update(item_fixture.id, session=dbsession, is_available=True)
        dbsession.refresh(item_fixture)
        dbsession.commit()
    return item_fixture


@pytest.fixture
def nonavailable_item(dbsession, item_fixture):
    """Item, не доступный для аренды.

    .. note::
        Очистка производится в dbsession.
    """
    if item_fixture.is_available == True:
        Item.update(item_fixture.id, session=dbsession, is_available=False)
        dbsession.refresh(item_fixture)
        dbsession.commit()
    return item_fixture


@pytest.fixture
def rentses(dbsession, available_item, authlib_user):
    """Экземпляр RentalSession, создаваемый в POST /rental_session.

    .. note::
        Очистка происходит в dbsession.
    """
    rent = RentalSession.create(
        session=dbsession,
        user_id=authlib_user.get("id"),
        item_id=available_item.id,
        reservation_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        status=RentStatus.RESERVED,
    )
    dbsession.add(rent)
    dbsession.commit()
    return rent


# Subtests (not call directly by pytest.)
def check_object_creation(db_model: BaseDbModel, session, num_of_creations: int=1) -> Generator[None, None, None]:
    """Проверяет создание объекта в БД после события."""
    start_len = db_model.query(session=session).count()
    yield
    end_len = db_model.query(session=session).count()
    assert (end_len - start_len) == num_of_creations, f'Убедитесь, что создается {num_of_creations} объектов {db_model} в БД!'

# TODO: Разбить тесты на блоки: по блоку на каждую ручку.

# def check_expiration_call(func_mock, session_id):  # TODO: Думаю, все же избыточно тестить каждую строчку кода. Только входное и выходное.
#     """Проверяет, что функция check_session_expiration вызывается 1 раз."""
#     try:
#         func_mock.assert_called_once_with(session_id)
#     except AssertionError:
#         raise NotImplementedError('Убедитесь, что функция check_session_expiration вызывается при вызове хэндлера!')


# Tests for POST /rental_session
def test_create_with_avail_item(dbsession, client, available_item, base_rentses_url, expire_mock):
    """Проверка логики метода с исходно доступным предметом в БД."""
    check_creation = check_object_creation(RentalSession, dbsession)  # TODO: Мб переписать как контекстный менеджер? Типа этот check же в контекст события...
    next(check_creation)
    response = client.post(f'{base_rentses_url}/{available_item.type_id}')
    assert response.status_code == status.HTTP_200_OK
    next(check_creation, None)
    dbsession.refresh(available_item)
    assert available_item.is_available == False, 'Убедитесь, что Item становится недоступен для аренды после создания RentalSession с ним!'


def test_create_with_no_avail_item(dbsession, client, nonavailable_item, base_rentses_url, expire_mock):
    """Проверка логики метода без исходно доступных предметов."""
    check_creation = check_object_creation(RentalSession, dbsession, num_of_creations=0)
    next(check_creation)
    response = client.post(f'{base_rentses_url}/{nonavailable_item.type_id}')
    assert response.status_code == status.HTTP_404_NOT_FOUND
    next(check_creation, None)
    dbsession.refresh(nonavailable_item)
    assert nonavailable_item.is_available == False, 'Убедитесь, что Item остается недоступен для аренды!'


def test_create_with_unexisting_id(dbsession, client, base_rentses_url, expire_mock):
    """Проверка логики метода с несуществующим item_type_id."""
    check_creation = check_object_creation(RentalSession, dbsession, num_of_creations=0)
    next(check_creation)
    try:
        unexisting_type_id = ItemType.query(session=dbsession).order_by(desc('id'))[0].id + 1
    except IndexError:
        unexisting_type_id = 1
    response = client.post(f'{base_rentses_url}/{unexisting_type_id}')
    assert response.status_code == status.HTTP_404_NOT_FOUND
    next(check_creation, None)


@pytest.mark.parametrize(
        'invalid_itemtype_id, right_status_code',
        [
            ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('he-he/hoho', status.HTTP_404_NOT_FOUND),
            (-1, status.HTTP_404_NOT_FOUND),
            ('', status.HTTP_405_METHOD_NOT_ALLOWED)],
        ids= ['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty'],
)
def test_create_with_invalid_id(dbsession, client, base_rentses_url, expire_mock, invalid_itemtype_id, right_status_code):
    """Проверка логики метода с невалидным item_type_id."""
    check_creation = check_object_creation(RentalSession, dbsession, num_of_creations=0)
    next(check_creation)
    response = client.post(f'{base_rentses_url}/{invalid_itemtype_id}')
    if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
    assert response.status_code == right_status_code
    next(check_creation, None)


def test_create_internal_server_error(monkeypatch, client, available_item, base_rentses_url):
    """Проверка логики обработки неожиданных ошибок."""
    def mock_db_error(*args, **kwargs):
        raise Exception("Database error")

    monkeypatch.setattr("rental_backend.routes.rental_session.Item.query", mock_db_error)
    response = client.post(f"{base_rentses_url}/{available_item.type_id}")
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_create_and_expire(dbsession, client, base_rentses_url, available_item, expiration_time_mock):
    """Проверка правильного срабатывания check_session_expiration."""
    response = client.post(f'{base_rentses_url}/{available_item.type_id}')
    assert response.status_code == status.HTTP_200_OK
    assert RentalSession.get(id=response.json()['id'], session=dbsession).status == RentStatus.CANCELED, 'Убедитесь, что по истечение RENTAL_SESSION_EXPIRY, аренда переходит в RentStatus.RESERVED!'



# Tests for PATCH /rental_session
# @pytest.mark.skip(reason='Пока что не до них')
@pytest.mark.parametrize(
    'payload, right_status_code, update_in_db',
    [
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
                "admin_close_id": 0,
            },
            status.HTTP_200_OK, True,
        ),
        (
            {"end_ts": "2025-04-18T23:32:30.589Z", "actual_return_ts": "2025-04-18T23:32:30.589Z", "admin_close_id": 0},
            status.HTTP_200_OK, True,
        ),
        (
            {"status": "reserved", "actual_return_ts": "2025-04-18T23:32:30.589Z", "admin_close_id": 0},
            status.HTTP_200_OK, True,
        ),
        ({"status": "reserved", "end_ts": "2025-04-18T23:32:30.589Z", "admin_close_id": 0}, status.HTTP_200_OK, True,),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
            },
            status.HTTP_200_OK, True,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
                "admin_close_id": 0,
                "extra": "oops!",
            },
            status.HTTP_200_OK, True,
        ),
        (
            {
                "status": "cringe",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
                "admin_close_id": 0,
            },
            status.HTTP_422_UNPROCESSABLE_ENTITY, False,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "he-he",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
                "admin_close_id": 0,
            },
            status.HTTP_422_UNPROCESSABLE_ENTITY, False,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "ha-ha",
                "admin_close_id": 0,
            },
            status.HTTP_422_UNPROCESSABLE_ENTITY, False,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
                "admin_close_id": "boba",
            },
            status.HTTP_422_UNPROCESSABLE_ENTITY, False,
        ),
        ({}, status.HTTP_409_CONFLICT, False,),
        (
            {"status": "reserved", "end_ts": None, "actual_return_ts": None, "admin_close_id": None},
            status.HTTP_409_CONFLICT, False,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": None,
                "admin_close_id": None,
            },
            status.HTTP_200_OK, True,
        ),
    ],
    ids=[
        'valid_new_payload',
        'valid_new_without_status',
        'valid_new_without_end_ts',
        'valid_new_without_actual_return_ts',
        'valid_new_without_admin_close_id',
        'valid_new_with_extra_field',
        'invalid_status',
        'invalid_end_ts',
        'inavalid_actual_return_ts',
        'invalid_admin_close_id',
        'empty_payload',
        'full_old_payload',
        'part_old_payload',
    ],
)
def test_payload_for_update_rental_session(
    dbsession, rentses, client, base_rentses_url, payload, right_status_code, update_in_db
):
    """Проверка ручки PATCH /itemtype на разные входные данные.
    
    Проверяются HTTP-коды и состояние записи в БД.
    """
    old_model_fields = model_to_dict(rentses)
    response = client.patch(f"{base_rentses_url}/{rentses.id}", json=payload)
    if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        pytest.xfail(reason='Ждут issue #39. Удалить маркер, когда баг будет устранен.')
    assert response.status_code == right_status_code
    dbsession.refresh(rentses)
    new_model_fields = model_to_dict(rentses)
    is_really_updated = old_model_fields != new_model_fields
    assert is_really_updated == update_in_db
