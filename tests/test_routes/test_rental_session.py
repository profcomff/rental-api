from typing import Tuple, List, Generator, Dict, Any
import datetime
from contextlib import contextmanager
# import pdb

import pytest
from starlette import status
from sqlalchemy.exc import StatementError, DataError
from sqlalchemy import desc

from rental_backend.models.base import BaseDbModel
from rental_backend.models.db import Item, RentalSession, ItemType, Event, Strike
from rental_backend.routes.rental_session import rental_session
from rental_backend.schemas.models import RentStatus
from rental_backend.exceptions import AlreadyExists
from tests.conftest import model_to_dict, make_url_query
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
def available_item(dbsession, item_fixture) -> Item:
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
def nonavailable_item(dbsession, item_fixture) -> Item:
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
def valid_update_payload() -> Dict[str, Any]:
    """Валидный словарь параметров для обновления RentalSession."""
    return {
        "status": "reserved",
        "end_ts": "2025-04-18T23:32:30.589Z",
        "actual_return_ts": "2025-04-18T23:32:30.589Z",
        "admin_close_id": 0,
    }


@pytest.fixture
def rentses(dbsession, available_item, authlib_user) -> RentalSession:
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
    Item.update(id=available_item.id, session=dbsession, is_available=False)
    dbsession.add(rent)
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
        reservation_ts=datetime.datetime.now(tz=datetime.timezone.utc),
        status=RentStatus.RESERVED,
    )
    Item.update(id=renting_item.id, session=dbsession, is_available=False)
    dbsession.add(rent)
    dbsession.commit()
    return rent


@pytest.fixture
def active_rentses(dbsession, rentses) -> RentalSession:
    """Начатая сессия аренды."""
    try:
        RentalSession.update(id=rentses.id, session=dbsession, status=RentStatus.ACTIVE)
    except AlreadyExists:
        return rentses
    dbsession.commit()
    return rentses


@pytest.fixture
def rentses_with_end_ts(dbsession, active_rentses) -> RentalSession:
    """RentalSession с end_ts не None."""
    RentalSession.update(id=active_rentses.id, session=dbsession, end_ts=datetime.datetime.now(tz=datetime.timezone.utc))
    dbsession.commit()
    return active_rentses


# Subtests (not call directly by pytest)
@contextmanager
def check_object_creation(db_model: BaseDbModel, session, num_of_creations: int=1) -> Generator[None, None, None]:
    """Проверяет создание объекта в БД после события."""
    start_len = db_model.query(session=session).count()
    yield
    end_len = db_model.query(session=session).count()
    assert (end_len - start_len) == num_of_creations, f'Убедитесь, что создается {num_of_creations} объектов {db_model.__name__} в БД!'


@contextmanager
def check_object_update(model_instance: BaseDbModel, session, **final_fields):  # TODO: написать и протестить в тестах
    """Проверяет обновление объекта в БД после события."""
    yield
    session.refresh(model_instance)
    for field in final_fields:
        old_field = final_fields[field]
        new_field = getattr(model_instance, field)
        assert old_field == new_field, f'Убедитесь, поле {field} модели {model_instance.__class__.__name__} в БД меняется (или нет) корректно!\nБыло -- {old_field}\nСтало -- {new_field}.'


# Tests for POST /rental-sessions/{item_type_id}
def test_create_with_avail_item(dbsession, client, available_item, base_rentses_url, expire_mock):
    """Проверка логики метода с исходно доступным предметом в БД."""
    with check_object_creation(RentalSession, dbsession):
        response = client.post(f'{base_rentses_url}/{available_item.type_id}')
        assert response.status_code == status.HTTP_200_OK
    dbsession.refresh(available_item)
    assert available_item.is_available == False, 'Убедитесь, что Item становится недоступен для аренды после создания RentalSession с ним!'


def test_create_with_no_avail_item(dbsession, client, nonavailable_item, base_rentses_url, expire_mock):
    """Проверка логики метода без исходно доступных предметов."""
    with check_object_creation(RentalSession, dbsession, num_of_creations=0):
        response = client.post(f'{base_rentses_url}/{nonavailable_item.type_id}')
        assert response.status_code == status.HTTP_404_NOT_FOUND
    dbsession.refresh(nonavailable_item)
    assert nonavailable_item.is_available == False, 'Убедитесь, что Item остается недоступен для аренды!'


def test_create_with_unexisting_id(dbsession, client, base_rentses_url, expire_mock):
    """Проверка логики метода с несуществующим item_type_id."""
    try:
        unexisting_type_id = ItemType.query(session=dbsession).order_by(desc('id'))[0].id + 1
    except IndexError:
        unexisting_type_id = 1
    with check_object_creation(RentalSession, dbsession, num_of_creations=0):
        response = client.post(f'{base_rentses_url}/{unexisting_type_id}')
        assert response.status_code == status.HTTP_404_NOT_FOUND


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
    with check_object_creation(RentalSession, dbsession, num_of_creations=0):
        response = client.post(f'{base_rentses_url}/{invalid_itemtype_id}')
        if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
        assert response.status_code == right_status_code


def test_create_internal_server_error(monkeypatch, dbsession, client, available_item, base_rentses_url):
    """Проверка логики обработки неожиданных ошибок."""
    def mock_db_error(*args, **kwargs):
        raise Exception("Database error")

    monkeypatch.setattr("rental_backend.routes.rental_session.Item.query", mock_db_error)
    with check_object_creation(RentalSession, dbsession, num_of_creations=0):
        response = client.post(f"{base_rentses_url}/{available_item.type_id}")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_create_and_expire(dbsession, client, base_rentses_url, available_item, expiration_time_mock):
    """Проверка правильного срабатывания check_session_expiration."""
    response = client.post(f'{base_rentses_url}/{available_item.type_id}')
    assert response.status_code == status.HTTP_200_OK
    assert RentalSession.get(id=response.json()['id'], session=dbsession).status == RentStatus.CANCELED, 'Убедитесь, что по истечение RENTAL_SESSION_EXPIRY, аренда переходит в RentStatus.RESERVED!'


# Tests for PATCH /rental-sessions/{session_id}/start
def test_start_success(dbsession, client, rentses, base_rentses_url):
    """Проверка логики метода с успешным стартом аренды."""
    with check_object_update(rentses, dbsession, status=RentStatus.ACTIVE):
        response = client.patch(f'{base_rentses_url}/{rentses.id}/start')
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize(
        'session_id, right_status_code',
        [
            ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('he-he/hoho', status.HTTP_404_NOT_FOUND),
            (-1, status.HTTP_404_NOT_FOUND),
            ('', status.HTTP_404_NOT_FOUND)],
        ids= ['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty'],
)
def test_start_with_invalid_id(dbsession, client, base_rentses_url, rentses, session_id, right_status_code):
    """Проверка логики метода с невалидным session_id."""
    with check_object_update(rentses, dbsession, status=rentses.status):
        response = client.patch(f'{base_rentses_url}/{session_id}/start')
        if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
        assert response.status_code == right_status_code


def test_start_with_unexisting_session(dbsession, client, base_rentses_url, rentses):
    """Проверка попытки старта несуществующей сессии аренды."""
    try:
        unexisting_id = RentalSession.query(session=dbsession).order_by(desc('id'))[0].id + 1
    except IndexError:
        unexisting_id = 1
    response = client.patch(f'{base_rentses_url}/{unexisting_id}/start')
    assert response.status_code == status.HTTP_404_NOT_FOUND


# Tests for PATCH /rental-sessions/{session_id}/return
def test_return_success(dbsession, client, active_rentses, base_rentses_url):
    """Проверка логики метода с успешным окончанием аренды."""
    avail_item = Item.get(id=active_rentses.item_id, session=dbsession)
    with check_object_update(active_rentses, dbsession, status=RentStatus.RETURNED), check_object_update(avail_item, dbsession, is_available=False):
        response = client.patch(f'{base_rentses_url}/{active_rentses.id}/return')
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize(
        'session_id, right_status_code',
        [
            ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('he-he/hoho', status.HTTP_404_NOT_FOUND),
            (-1, status.HTTP_404_NOT_FOUND),
            ('', status.HTTP_404_NOT_FOUND)
        ],
        ids= ['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty'],
)
def test_return_with_invalid_id(dbsession, client, base_rentses_url, rentses, session_id, right_status_code):
    """Проверка логики метода с невалидным session_id."""
    with check_object_update(rentses, dbsession, status=rentses.status):
        response = client.patch(f'{base_rentses_url}/{session_id}/return')
        if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
        assert response.status_code == right_status_code


def test_return_with_unexisting_session(dbsession, client, base_rentses_url, rentses):
    """Проверка попытки старта несуществующей сессии аренды."""
    try:
        unexisting_id = RentalSession.query(session=dbsession).order_by(desc('id'))[0].id + 1
    except IndexError:
        unexisting_id = 1
    response = client.patch(f'{base_rentses_url}/{unexisting_id}/return')
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_return_inactive(dbsession, client, rentses, base_rentses_url):
    """Проверка логики метода с попыткой закончить неактивную аренды."""
    # check_creation = check_object_creation(RentalSession, dbsession)  # TODO: Мб переписать как контекстный менеджер? Типа этот check же в контекст события...
    # next(check_creation)
    # old_rent_status = rentses.status
    with check_object_update(rentses, dbsession, status=rentses.status):
        response = client.patch(f'{base_rentses_url}/{rentses.id}/return')
        assert response.status_code == status.HTTP_409_CONFLICT
    # dbsession.refresh(rentses)
    # assert rentses.status == old_rent_status, 'Убедитесь, что при попытке завершить неактивную аренду ее статус не меняется!'


@pytest.mark.parametrize(
        'with_strike, strike_reason, right_status_code, strike_created',
        [
            (None, None, status.HTTP_200_OK, False),
            (True, 'Test case', status.HTTP_200_OK, True),
            (True, None, status.HTTP_200_OK, True),
            (False, 'Test case', status.HTTP_200_OK, False),
            (3, 'Test case', status.HTTP_422_UNPROCESSABLE_ENTITY, False),
            ('hihi', 'Test case', status.HTTP_422_UNPROCESSABLE_ENTITY, False),
            ('hoho/haha', 'Test case', status.HTTP_422_UNPROCESSABLE_ENTITY, False),
        ],
        ids=['empty', 'full_valid', 'only_with', 'only_reason', 'invalid_with_big_num', 'invalid_with_text', 'invalid_with_trailing_slash']
)
def test_return_with_strike(dbsession, client, base_rentses_url, active_rentses, with_strike, strike_reason, right_status_code, strike_created):
    """Проверяет завершение аренды со страйком."""
    query_dict = dict()
    if with_strike is not None:
        query_dict['with_strike'] = with_strike
    if strike_reason is not None:
        query_dict['strike_reason'] = strike_reason
    strike_query = make_url_query(query_dict)
    num_of_creations = 1 if strike_created else 0
    # check_creation = check_object_creation(Strike, dbsession, num_of_creations=num_of_creations)
    # next(check_creation)
    with check_object_creation(Strike, dbsession, num_of_creations):
        response = client.patch(f'{base_rentses_url}/{active_rentses.id}/return{strike_query}')
        assert response.status_code == right_status_code
    # next(check_creation, None)


def test_return_with_set_end_ts(dbsession, client, base_rentses_url, rentses_with_end_ts):
    """Проверяет, что при обновлении RentalSession с end_ts не None сохраняется именно существующий, а не создается новый."""
    # old_end_ts = rentses_with_end_ts.end_ts
    with check_object_update(rentses_with_end_ts, dbsession, end_ts=rentses_with_end_ts.end_ts):
        response = client.patch(f'{base_rentses_url}/{rentses_with_end_ts.id}/return')
        assert response.status_code == status.HTTP_200_OK
    # dbsession.refresh(rentses_with_end_ts)
    # assert rentses_with_end_ts.end_ts == old_end_ts, 'Убедитесь, что при завершении аренды end_ts не меняется, если он не был None!'


# Tests for GET /rental-sessions/user/{user_id}
def test_get_for_user_success(dbsession, client, base_rentses_url, rentses):
    """Попытка успешно получить список аренд пользователя."""
    response = client.get(f'{base_rentses_url}/user/{rentses.user_id}')
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == len(RentalSession.query(session=dbsession).filter(RentalSession.user_id == rentses.user_id).all()), 'Убедитесь, что возвращаются все аренды пользователя!'


@pytest.mark.parametrize(
        'user_id, right_status_code',
        [
            ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('he-he/hoho', status.HTTP_404_NOT_FOUND),
            (-1, status.HTTP_200_OK),
            ('', status.HTTP_422_UNPROCESSABLE_ENTITY)
        ],
        ids= ['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty'],
)
def test_get_for_user_with_invalid_id(dbsession, client, base_rentses_url, rentses, user_id, right_status_code):
    """Проверка логики метода с невалидным user_id."""
    response = client.get(f'{base_rentses_url}/user/{user_id}')
    if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
    assert response.status_code == right_status_code
    if right_status_code == status.HTTP_200_OK:
        returned_queue = response.json()
        assert isinstance(returned_queue, list), 'Убедитесь, что возвращаемый объект типа List!'
        assert len(returned_queue) == 0, 'Убедитесь, что при передаче невалидного user_id возвращается пустой список.'


def test_get_for_user_internal_server_error(monkeypatch, client, base_rentses_url, rentses):
    """Проверяет поведение хэндлера при появлении непредвиденной ошибки."""
    def mock_db_error(*args, **kwargs):
        raise Exception("Database error")

    monkeypatch.setattr("rental_backend.routes.rental_session.RentalSession.query", mock_db_error)
    response = client.get(f'{base_rentses_url}/user/{rentses.user_id}')
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# Tests for GET /rental-sessions/{session_id}
def test_retrieve_success(dbsession, client, base_rentses_url, rentses):
    """Проверяем успешное получение сессии аренды."""
    response = client.get(f'{base_rentses_url}/{rentses.id}')
    assert response.status_code == status.HTTP_200_OK
    assert rentses == RentalSession.get(id=response.json()['id'], session=dbsession)

@pytest.mark.xfail(reason='Ждет issue #40. Потом удалить маркер и проверить тесты.')
@pytest.mark.parametrize(
        'session_id, right_status_code',
        [
            ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('he-he/hoho', status.HTTP_404_NOT_FOUND),
            (-1, status.HTTP_200_OK),
            ('', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('-1?hoho=hihi', status.HTTP_422_UNPROCESSABLE_ENTITY)
        ],
        ids= ['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty', 'excess_query'],
)
def test_retrieve_invalid_id(dbsession, client, base_rentses_url, rentses, session_id, right_status_code):
    """Проверка получения сессии по невалидному URL-path."""
    response = client.get(f'{base_rentses_url}/{rentses.id}')
    assert response.status_code == right_status_code
    if right_status_code == status.HTTP_200_OK:
        assert response.json()['id'] == rentses.id, 'Убедитесь, что возвращается та же сессия, что и запрашивается!'


def test_retrieve_internal_server_error(monkeypatch, client, base_rentses_url, rentses):
    """Проверяет поведение хэндлера при появлении непредвиденной ошибки."""
    def mock_db_error(*args, **kwargs):
        raise Exception("Database error")

    monkeypatch.setattr("rental_backend.routes.rental_session.RentalSession.get", mock_db_error)
    response = client.get(f'{base_rentses_url}/{rentses.id}')
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# Tests for PATCH /rental-sessions/{session_id}
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
def test_update_payload(
    dbsession, rentses, client, base_rentses_url, payload, right_status_code, update_in_db
):
    """Проверка поведения при разном теле запроса."""
    old_model_fields = model_to_dict(rentses)
    response = client.patch(f"{base_rentses_url}/{rentses.id}", json=payload)
    if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        pytest.xfail(reason='Ждут issue #39. Удалить маркер, когда баг будет устранен.')
    assert response.status_code == right_status_code
    dbsession.refresh(rentses)
    new_model_fields = model_to_dict(rentses)
    is_really_updated = old_model_fields != new_model_fields
    assert is_really_updated == update_in_db


@pytest.mark.parametrize(
        'session_id, right_status_code',
        [
            ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('he-he/hoho', status.HTTP_404_NOT_FOUND),
            (-1, status.HTTP_404_NOT_FOUND),
            ('', status.HTTP_405_METHOD_NOT_ALLOWED),
            ('-1?hoho=hihi', status.HTTP_404_NOT_FOUND)
        ],
        ids= ['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty', 'excess_query'],
)
def test_update_invalid_id(dbsession, client, base_rentses_url, rentses, valid_update_payload, session_id, right_status_code):
    """Проверка обновления сессии по невалидному URL-path."""
    response = client.patch(f'{base_rentses_url}/{session_id}', json=valid_update_payload)
    assert response.status_code == right_status_code


def test_update_internal_server_error(mocker, client, base_rentses_url, rentses, valid_update_payload):
    """Проверяет поведение хэндлера при появлении непредвиденной ошибки."""
    # def mock_db_error(*args, **kwargs):
    #     raise Exception("Database error")

    error_func = mocker.patch("rental_backend.routes.rental_session.RentalSession.get", side_effect=Exception('Database error'))
    # pdb.set_trace()
    response = client.patch(f'{base_rentses_url}/{rentses.id}', json=valid_update_payload)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR  # TODO: также добавить такую (и в остальных местах) проверку вызова мок-объекта (что падает именно из-за него).
    assert error_func.call_count == 1, 'Убедитесь, что ошибка выпадает именно при попытке вызвать RentalSession.get!'


# Tests for GET /rental-sessions
@pytest.mark.parametrize(
    'is_reserved, is_canceled, is_dismissed, is_overdue, is_returned, is_active, right_status_code',
    [
        (True, True, True, True, True, True, status.HTTP_200_OK),
        (None, True, True, True, True, True, status.HTTP_200_OK),
        (True, None, True, True, True, True, status.HTTP_200_OK),
        (True, True, None, True, True, True, status.HTTP_200_OK),
        (True, True, True, None, True, True, status.HTTP_200_OK),
        (True, True, True, True, None, True, status.HTTP_200_OK),
        (True, True, True, True, True, None, status.HTTP_200_OK),
        ('haha', True, True, True, True, True, status.HTTP_422_UNPROCESSABLE_ENTITY),
        (True, '', True, True, True, True, status.HTTP_422_UNPROCESSABLE_ENTITY),
        (True, True, -1, True, True, True, status.HTTP_422_UNPROCESSABLE_ENTITY),
        (True, True, True, 4, True, True, status.HTTP_422_UNPROCESSABLE_ENTITY),
        (True, True, True, True, 5, True, status.HTTP_422_UNPROCESSABLE_ENTITY),
        (True, True, True, True, True, 6, status.HTTP_422_UNPROCESSABLE_ENTITY),
        (None, None, None, None, None, None, status.HTTP_200_OK),
        (False, False, False, False, False, False, status.HTTP_200_OK),
    ],
    ids=[
        'valid_all',
        'valid_without_is_reserved',
        'valid_without_is_canceled',
        'valid_without_is_dismissed',
        'valid_without_is_overdue',
        'valid_without_is_returned',
        'valid_without_is_active',
        'invalid_is_reserved',
        'invalid_is_canceled',
        'invalid_is_dismissed',
        'invalid_is_overdue',
        'invalid_is_returned',
        'invalid_is_active',
        'valid_empty',
        'valid_all_False',
    ],
)
def test_get_url_query(dbsession, client, base_rentses_url, rentses, is_reserved, is_canceled, is_dismissed, is_overdue, is_returned, is_active, right_status_code):
    """Проверка получения сессий при разных URL-query."""
    query_data = dict()
    if is_reserved is not None:
        query_data['is_reserved'] = is_reserved
    if is_canceled is not None:
        query_data['is_canceled'] = is_canceled
    if is_dismissed is not None:
        query_data['is_dismissed'] = is_dismissed
    if is_overdue is not None:
        query_data['is_overdue'] = is_overdue
    if is_returned is not None:
        query_data['is_returned'] = is_returned
    if is_active is not None:
        query_data['is_active'] = is_active
    print(query_data)
    # pdb.set_trace()
    response = client.get(f'{base_rentses_url}{make_url_query(query_data)}')
    assert response.status_code == right_status_code
    if right_status_code == status.HTTP_200_OK:
        assert isinstance(response.json(), list)


def test_get_query_extra_param(dbsession, client, base_rentses_url, rentses):
    """Проверка запроса с непредусмотренным параметром в URL-query."""
    extra_response = client.get(f'{base_rentses_url}?hehe=True')
    assert extra_response.status_code == status.HTTP_200_OK
    valid_response = client.get(f'{base_rentses_url}')
    assert len(extra_response.json()) == len(valid_response.json()), 'Убедитесь, что экстра параметр не меняет поведения хэндлера!'


# Tests for DELETE /rental-sessions/{session_id}/cancel
def test_cancel_success(dbsession, client, base_rentses_url, rentses):
    """Проверяет успешный сценарий отмены аренды."""
    with check_object_update(rentses, dbsession, status=RentStatus.CANCELED), check_object_update(Item.get(id=rentses.item_id, session=dbsession), dbsession, is_available=True):
        response = client.delete(f'{base_rentses_url}/{rentses.id}/cancel')
        assert response.status_code == status.HTTP_200_OK, 'Убедитесь, что аренду можно отменить!'
    # dbsession.refresh(rentses)
    # assert rentses.status == RentStatus.CANCELED, 'Убедитесь, что аренда переводится в статус RentStatus.CANCELED!'
    # assert Item.get(id=rentses.item_id, session=dbsession).is_available == True, 'Убедитесь, что Item становится доступен для повторной аренды!'


@pytest.mark.parametrize(
        'session_id, right_status_code',
        [
            ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
            ('he-he/hoho', status.HTTP_404_NOT_FOUND),
            (-1, status.HTTP_404_NOT_FOUND),
            ('', status.HTTP_404_NOT_FOUND),
            ('-1?hoho=hihi', status.HTTP_405_METHOD_NOT_ALLOWED)
        ],
        ids= ['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty', 'excess_query'],
)
def test_cancel_invalid(client, base_rentses_url, session_id, right_status_code):
    """Проверяет случай запроса по невалидному session_id."""
    response = client.delete(f'{base_rentses_url}/{session_id}/cancel')
    assert response.status_code == right_status_code


def test_cancel_wrong_user(dbsession, rentses, base_rentses_url, another_client):  # FIXME: не работает... Вопрос: работает ли мок аутентификации из фикстуры? Как? Почему запрос проходит?(
    """Проверяет случай запроса от пользователя, который не привязан к данной сессии."""
    # old_status = rentses.status
    # pdb.set_trace()
    with check_object_update(rentses, dbsession, status=rentses.status):
        response = another_client.delete(f'{base_rentses_url}/{rentses.id}/cancel')
        assert response.status_code == status.HTTP_403_FORBIDDEN, 'Убедитесь, что не создатель аренды не может ее отменить!'
    # dbsession.refresh(rentses)
    # assert rentses.status == old_status, 'Убедитесь, что статус аренды не меняется при запросе не от создателя аренды!'


@pytest.mark.parametrize(
    'new_wrong_status',
    [RentStatus.ACTIVE, RentStatus.CANCELED, RentStatus.OVERDUE, RentStatus.RETURNED, RentStatus.DISMISSED],
    ids=['active', 'canceled', 'overdue', 'returned', 'dismissed']
)
def test_cancel_wrong_status(dbsession, client, base_rentses_url, rentses, new_wrong_status):
    """Проверяет случай запроса на отмену незарезервированной сессии."""
    RentalSession.update(id=rentses.id, session=dbsession, status=new_wrong_status)
    dbsession.commit()
    dbsession.refresh(rentses)
    # pdb.set_trace()
    with check_object_update(rentses, dbsession, status=new_wrong_status):
        response = client.delete(f'{base_rentses_url}/{rentses.id}/cancel')
        assert response.status_code == status.HTTP_403_FORBIDDEN, 'Убедитесь, что нельзя отменить незарезервированную сессию!'
    # assert rentses.status == new_wrong_status, 'Убедитесь, что статус аренды не меняется при некорректном запросе!'


def test_cancel_internal_server_error(mocker, dbsession, client, base_rentses_url, rentses):
    """Проверяет случай возникновения неожиданной ошибки."""
    # def mock_db_error(*args, **kwargs):
    #     raise Exception("Database error")

    error_func = mocker.patch("rental_backend.routes.rental_session.RentalSession.get", side_effect=Exception('Database error'))
    # pdb.set_trace()
    response = client.delete(f'{base_rentses_url}/{rentses.id}/cancel')
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR  # TODO: также добавить такую (и в остальных местах) проверку вызова мок-объекта (что падает именно из-за него).
    assert error_func.call_count == 1, 'Убедитесь, что ошибка выпадает именно при попытке вызвать RentalSession.get!'
