from typing import Tuple, List, Generator, Dict
import datetime

import pytest
from starlette import status
from sqlalchemy.exc import StatementError, DataError
from sqlalchemy import desc

from rental_backend.models.base import BaseDbModel
from rental_backend.models.db import Item, RentalSession, ItemType, Event, Strike
from rental_backend.routes.rental_session import rental_session
from rental_backend.schemas.models import RentStatus
from rental_backend.exceptions import AlreadyExists
from conftest import model_to_dict
# TODO: подумать над багом при teardown test: при ошибке в teardown (точно, если sqlalchemy), у меня не затираются тестовые объекты => некритично, но желательно починить!


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


@pytest.fixture
def active_rentses(dbsession, rentses):
    """Начатая сессия аренды."""
    try:
        RentalSession.update(id=rentses.id, session=dbsession, status=RentStatus.ACTIVE)
    except AlreadyExists:
        return rentses
    dbsession.commit()
    return rentses


@pytest.fixture
def rentses_with_end_ts(dbsession, rentses):
    """RentalSession с end_ts не None."""
    RentalSession.update(id=rentses.id, session=dbsession, end_ts=datetime.datetime.now(tz=datetime.timezone.utc))
    dbsession.commit()
    return rentses


# Subtests (not call directly by pytest.)
def check_object_creation(db_model: BaseDbModel, session, num_of_creations: int=1) -> Generator[None, None, None]:
    """Проверяет создание объекта в БД после события."""
    start_len = db_model.query(session=session).count()
    yield
    end_len = db_model.query(session=session).count()
    assert (end_len - start_len) == num_of_creations, f'Убедитесь, что создается {num_of_creations} объектов {db_model.__name__} в БД!'

# TODO: Разбить тесты на блоки: по блоку на каждую ручку.

# def check_expiration_call(func_mock, session_id):  # TODO: Думаю, все же избыточно тестить каждую строчку кода. Только входное и выходное.
#     """Проверяет, что функция check_session_expiration вызывается 1 раз."""
#     try:
#         func_mock.assert_called_once_with(session_id)
#     except AssertionError:
#         raise NotImplementedError('Убедитесь, что функция check_session_expiration вызывается при вызове хэндлера!')


# Tests for POST /rental_session/{item_type_id}
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


def test_create_internal_server_error(monkeypatch, dbsession, client, available_item, base_rentses_url):
    """Проверка логики обработки неожиданных ошибок."""
    def mock_db_error(*args, **kwargs):
        raise Exception("Database error")

    monkeypatch.setattr("rental_backend.routes.rental_session.Item.query", mock_db_error)
    check_creation = check_object_creation(RentalSession, dbsession, num_of_creations=0)
    next(check_creation)
    response = client.post(f"{base_rentses_url}/{available_item.type_id}")
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    next(check_creation, None)


def test_create_and_expire(dbsession, client, base_rentses_url, available_item, expiration_time_mock):
    """Проверка правильного срабатывания check_session_expiration."""
    response = client.post(f'{base_rentses_url}/{available_item.type_id}')
    assert response.status_code == status.HTTP_200_OK
    assert RentalSession.get(id=response.json()['id'], session=dbsession).status == RentStatus.CANCELED, 'Убедитесь, что по истечение RENTAL_SESSION_EXPIRY, аренда переходит в RentStatus.RESERVED!'


# Tests for PATCH /rental_session/{session_id}/start
def test_start_success(dbsession, client, rentses, base_rentses_url):
    """Проверка логики метода с успешным стартом аренды."""
    # check_creation = check_object_creation(RentalSession, dbsession)  # TODO: Мб переписать как контекстный менеджер? Типа этот check же в контекст события...
    # next(check_creation)
    response = client.patch(f'{base_rentses_url}/{rentses.id}/start')
    assert response.status_code == status.HTTP_200_OK
    dbsession.refresh(rentses)
    assert rentses.status == RentStatus.ACTIVE, 'Убедитесь, что при старте аренды сессия переводится в RentStatus.ACTIVE!'
    # next(check_creation, None)
    # dbsession.refresh(available_item)
    # assert available_item.is_available == False, 'Убедитесь, что Item становится недоступен для аренды после создания RentalSession с ним!'


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
    # check_creation = check_object_creation(RentalSession, dbsession, num_of_creations=0)  # TODO: мб сделать такой же, но на апдейт?
    # next(check_creation)
    response = client.patch(f'{base_rentses_url}/{session_id}/start')
    if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
    assert response.status_code == right_status_code
    dbsession.refresh(rentses)
    assert rentses.status != RentStatus.ACTIVE, 'Убедитесь, что при невалидном запросе сессия не переводится в RentStatus.ACTIVE!'
    # next(check_creation, None)


def test_start_with_unexisting_session(dbsession, client, base_rentses_url, rentses):  # TODO: мб проводить проверку изменений в БД объекта? Это же критично!
    """Проверка попытки старта несуществующей сессии аренды."""
    try:
        unexisting_id = RentalSession.query(session=dbsession).order_by(desc('id'))[0].id + 1
    except IndexError:
        unexisting_id = 1
    response = client.patch(f'{base_rentses_url}/{unexisting_id}/start')
    assert response.status_code == status.HTTP_404_NOT_FOUND


# Tests for PATCH /rental_session/{session_id}/return
def test_return_success(dbsession, client, active_rentses, base_rentses_url):
    """Проверка логики метода с успешным окончанием аренды."""
    # check_creation = check_object_creation(RentalSession, dbsession)  # TODO: Мб переписать как контекстный менеджер? Типа этот check же в контекст события...
    # next(check_creation)
    response = client.patch(f'{base_rentses_url}/{active_rentses.id}/return')
    assert response.status_code == status.HTTP_200_OK
    dbsession.refresh(active_rentses)
    assert active_rentses.status == RentStatus.RETURNED, 'Убедитесь, что при окончании аренды сессия переводится в RentStatus.RETURNED!'
    # next(check_creation, None)
    # dbsession.refresh(available_item)
    # assert available_item.is_available == False, 'Убедитесь, что Item становится недоступен для аренды после создания RentalSession с ним!'


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
    # check_creation = check_object_creation(RentalSession, dbsession, num_of_creations=0)  # TODO: мб сделать такой же, но на апдейт?
    # next(check_creation)
    response = client.patch(f'{base_rentses_url}/{session_id}/return')
    if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
    assert response.status_code == right_status_code
    dbsession.refresh(rentses)
    assert rentses.status != RentStatus.ACTIVE, 'Убедитесь, что при невалидном запросе сессия не переводится в RentStatus.ACTIVE!'
    # next(check_creation, None)


def test_return_with_unexisting_session(dbsession, client, base_rentses_url, rentses):  # TODO: мб проводить проверку изменений в БД объекта? Это же критично!
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
    response = client.patch(f'{base_rentses_url}/{rentses.id}/return')
    if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        pytest.xfail(reason='Ждет хэндлер под ошибку InactiveSession. Удалить, как появиться и переписать тест с проверкой возвращения нужного HTTP-статуса.')
    dbsession.refresh(rentses)
    assert rentses.status == RentStatus.ACTIVE, 'Убедитесь, что при старте аренды сессия переводится в RentStatus.ACTIVE!'


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
    num_of_creations = 1 if strike_created else 0
    check_creation = check_object_creation(Strike, dbsession, num_of_creations=num_of_creations)
    next(check_creation)
    query_dict = dict()
    if with_strike is not None:
        query_dict['with_strike'] = with_strike
    if strike_reason is not None:
        query_dict['strike_reason'] = strike_reason
    strike_query = make_url_query(query_dict)
    response = client.patch(f'{base_rentses_url}/{active_rentses.id}/return{strike_query}')
    assert response.status_code == right_status_code
    next(check_creation, None)  # FIXME: Проверить, как станет известно по добавлению await к create_strike.


def test_return_with_set_end_ts(dbsession, client, base_rentses_url, rentses_with_end_ts):
    """Проверяет, что при обновлении RentalSession с end_ts не None сохраняется именно существующий, а не создается новый."""
    old_end_ts = rentses_with_end_ts.end_ts
    response = client.patch(f'{base_rentses_url}/{rentses_with_end_ts.id}/return')
    dbsession.refresh(rentses_with_end_ts)
    assert rentses_with_end_ts.end_ts == old_end_ts, 'Убедитесь, что при завершении аренды end_ts не меняется, если он не был None!'


# Tests for GET /rental_session/user/{user_id}
# @pytest.mark.parametrize(
#         'user_id, right_status_code',
#         [
#             ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
#             ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
#             ('he-he/hoho', status.HTTP_404_NOT_FOUND),
#             (-1, status.HTTP_404_NOT_FOUND),
#             ('', status.HTTP_404_NOT_FOUND)
#         ],
#         ids= ['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty'],
# )
# def test_get_for_user_with_invalid_id(dbsession, client, base_rentses_url, rentses, user_id, right_status_code):
#     """Проверка логики метода с невалидным user_id."""
#     response = client.patch(f'{base_rentses_url}/user/{user_id}')
#     if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
#         pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
#     assert response.status_code == right_status_code
#     dbsession.refresh(rentses)
#     assert rentses.status != RentStatus.ACTIVE, 'Убедитесь, что при невалидном запросе сессия не переводится в RentStatus.ACTIVE!'


# Tests for PATCH /rental_session/{session_id}
# TODO: добавить сюда тесты с невалидными URL + HTTP_500.
@pytest.mark.skip(reason='Пока что не до них')
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
