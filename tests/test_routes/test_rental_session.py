import datetime
from contextlib import contextmanager
from typing import Generator

import pytest
from sqlalchemy import desc
from starlette import status

from rental_backend.models.base import BaseDbModel
from rental_backend.models.db import Item, ItemType, RentalSession, Strike
from rental_backend.routes.rental_session import rental_session
from rental_backend.schemas.models import RentStatus
from tests.conftest import model_to_dict


obj_prefix: str = rental_session.prefix


# Subtests (not call directly by pytest)
@contextmanager
def check_object_creation(db_model: BaseDbModel, session, num_of_creations: int = 1) -> Generator[None, None, None]:
    """Проверяет создание объекта в БД после события."""
    start_len = db_model.query(session=session).count()
    yield
    end_len = db_model.query(session=session).count()
    assert (
        end_len - start_len
    ) == num_of_creations, f'Убедитесь, что создается {num_of_creations} объектов {db_model.__name__} в БД!'


@contextmanager
def check_object_update(model_instance: BaseDbModel, session, **final_fields):
    """Проверяет обновление объекта в БД после события."""
    yield
    session.refresh(model_instance)
    for field in final_fields:
        expecting_field = final_fields[field]
        current_field = getattr(model_instance, field)
        assert (
            expecting_field == current_field
        ), f'Убедитесь, поле {field} модели {model_instance.__class__.__name__} в БД меняется (или нет) корректно!\nБыло -- {expecting_field}\nСтало -- {current_field}.'


# Tests for POST /rental-sessions/{item_type_id}
@pytest.mark.usefixtures('expire_mock')
@pytest.mark.parametrize(
    'start_item_avail, end_item_avail, itemtype_list_ind, right_status_code, num_of_creations',
    [
        (True, False, 0, status.HTTP_200_OK, 1),
        (False, False, 0, status.HTTP_404_NOT_FOUND, 0),
        (True, True, 1, status.HTTP_404_NOT_FOUND, 0),
    ],
    ids=['avail_item', 'not_avail_item', 'unexisting_itemtype'],
)
def test_create_with_diff_item(
    dbsession,
    client,
    item_fixture,
    base_rentses_url,
    start_item_avail,
    end_item_avail,
    itemtype_list_ind,
    right_status_code,
    num_of_creations,
):
    """Проверка старта аренды разных Item от разных ItemType."""
    item_fixture.is_available = start_item_avail
    dbsession.add(item_fixture)
    dbsession.commit()
    try:
        type_id = ItemType.query(session=dbsession).all()[itemtype_list_ind].id
    except IndexError:
        type_id = ItemType.query(session=dbsession).order_by(desc('id'))[0].id + 1
    with (
        check_object_creation(RentalSession, dbsession, num_of_creations=num_of_creations),
        check_object_update(item_fixture, session=dbsession, is_available=end_item_avail),
    ):
        response = client.post(f'{base_rentses_url}/{type_id}')
        assert response.status_code == right_status_code


@pytest.mark.usefixtures('expire_mock')
@pytest.mark.parametrize(
    'invalid_itemtype_id, right_status_code',
    [
        ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('he-he/hoho', status.HTTP_404_NOT_FOUND),
        (-1, status.HTTP_404_NOT_FOUND),
        ('', status.HTTP_405_METHOD_NOT_ALLOWED),
    ],
    ids=['text', 'hyphen', 'subpath', 'negative_num', 'empty'],
)
def test_create_with_invalid_id(dbsession, client, base_rentses_url, invalid_itemtype_id, right_status_code):
    """Проверка логики метода с невалидным item_type_id."""
    with check_object_creation(RentalSession, dbsession, num_of_creations=0):
        response = client.post(f'{base_rentses_url}/{invalid_itemtype_id}')
        if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
        assert response.status_code == right_status_code


@pytest.mark.usefixtures('expiration_time_mock')
def test_create_and_expire(dbsession, client, base_rentses_url, item_fixture):
    """Проверка правильного срабатывания check_session_expiration."""
    item_fixture.is_available = True
    dbsession.add(item_fixture)
    dbsession.commit()
    response = client.post(f'{base_rentses_url}/{item_fixture.type_id}')
    assert response.status_code == status.HTTP_200_OK
    assert (
        RentalSession.get(id=response.json()['id'], session=dbsession).status == RentStatus.OVERDUE
    ), 'Убедитесь, что по истечение RENTAL_SESSION_EXPIRY, аренда переходит в RentStatus.OVERDUE!'


# Tests for PATCH /rental-sessions/{session_id}/start
@pytest.mark.parametrize(
    'session_id, right_status_code',
    [
        (0, status.HTTP_200_OK),
        ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('he-he/hoho', status.HTTP_404_NOT_FOUND),
        (-2, status.HTTP_404_NOT_FOUND),
        ('', status.HTTP_404_NOT_FOUND),
    ],
    ids=['success', 'text', 'hyphen', 'subpath', 'unexisting_id', 'empty'],
)
def test_start_with_diff_id(dbsession, client, rentses, base_rentses_url, session_id, right_status_code):
    """Проверка попытки старта аренды по разным session_id."""
    try:
        id = RentalSession.query(session=dbsession).all()[session_id].id
        new_status = RentStatus.ACTIVE
    except (IndexError, TypeError):
        id = session_id
        new_status = rentses.status
    with check_object_update(rentses, dbsession, status=new_status):
        response = client.patch(f'{base_rentses_url}/{id}/start')
        if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
        assert response.status_code == right_status_code


# Tests for PATCH /rental-sessions/{session_id}/return
@pytest.mark.parametrize(
    'session_id, right_status_code',
    [
        (0, status.HTTP_200_OK),
        ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('he-he/hoho', status.HTTP_404_NOT_FOUND),
        (-2, status.HTTP_404_NOT_FOUND),
        ('', status.HTTP_404_NOT_FOUND),
    ],
    ids=['success', 'text', 'hyphen', 'subpath', 'unexisting_id', 'empty'],
)
def test_return_with_diff_id(dbsession, client, active_rentses, base_rentses_url, session_id, right_status_code):
    """Проверка попытки завершить сессию по разным id."""
    try:
        id = RentalSession.query(session=dbsession).all()[session_id].id
        new_status = RentStatus.RETURNED
    except (IndexError, TypeError):
        id = session_id
        new_status = active_rentses.status
    with check_object_update(active_rentses, dbsession, status=new_status):
        response = client.patch(f'{base_rentses_url}/{id}/return')
        if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
        assert response.status_code == right_status_code


def test_return_inactive(dbsession, client, rentses, base_rentses_url):
    """Проверка логики метода с попыткой закончить неактивную аренды."""
    with check_object_update(rentses, dbsession, status=rentses.status):
        response = client.patch(f'{base_rentses_url}/{rentses.id}/return')
        assert response.status_code == status.HTTP_409_CONFLICT


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
    ids=[
        'empty',
        'full_valid',
        'only_with',
        'only_reason',
        'invalid_with_big_num',
        'invalid_with_text',
        'invalid_with_trailing_slash',
    ],
)
def test_return_with_strike(
    dbsession, client, base_rentses_url, active_rentses, with_strike, strike_reason, right_status_code, strike_created
):
    """Проверяет завершение аренды со страйком."""
    query_dict = dict()
    if with_strike is not None:
        query_dict['with_strike'] = with_strike
    if strike_reason is not None:
        query_dict['strike_reason'] = strike_reason
    num_of_creations = 1 if strike_created else 0
    with check_object_creation(Strike, dbsession, num_of_creations):
        response = client.patch(f'{base_rentses_url}/{active_rentses.id}/return', params=query_dict)
        assert response.status_code == right_status_code


def test_return_with_set_end_ts(dbsession, client, base_rentses_url, active_rentses):
    """Проверяет, что при обновлении RentalSession с end_ts не None сохраняется именно существующий, а не создается новый."""
    active_rentses.end_ts = datetime.datetime.now(tz=datetime.timezone.utc)
    dbsession.add(active_rentses)
    dbsession.commit()
    with check_object_update(active_rentses, dbsession, end_ts=active_rentses.end_ts):
        response = client.patch(f'{base_rentses_url}/{active_rentses.id}/return')
        assert response.status_code == status.HTTP_200_OK


# Tests for GET /rental-sessions/user/{user_id}
@pytest.mark.usefixtures('rentses')
@pytest.mark.parametrize(
    'user_id, right_status_code',
    [
        (0, status.HTTP_200_OK),  # id=0 -- это id из authlib_user.
        ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('he-he/hoho', status.HTTP_404_NOT_FOUND),
        (-2, status.HTTP_200_OK),
        ('', status.HTTP_422_UNPROCESSABLE_ENTITY),
    ],
    ids=['success', 'text', 'hyphen', 'subpath', 'unexisting_id', 'empty'],
)
def test_get_for_user_with_diff_id(dbsession, client, base_rentses_url, user_id, right_status_code):
    """Проверка логики метода с разным user_id."""
    response = client.get(f'{base_rentses_url}/user/{user_id}')
    if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        pytest.xfail(reason='Ждет issue #40. Удалить маркер и проверить работоспособность.')
    assert response.status_code == right_status_code
    if right_status_code == status.HTTP_200_OK:
        returned_queue = response.json()
        assert isinstance(returned_queue, list), 'Убедитесь, что возвращаемый объект типа List!'
        assert len(returned_queue) == len(
            RentalSession.query(session=dbsession).filter(RentalSession.user_id == user_id).all()
        )


# Tests for GET /rental-sessions/{session_id}
@pytest.mark.usefixtures('rentses')
@pytest.mark.parametrize(
    'session_id, right_status_code',
    [
        (0, status.HTTP_200_OK),
        ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('he-he/hoho', status.HTTP_404_NOT_FOUND),
        (-2, status.HTTP_404_NOT_FOUND),
        ('-1?hoho=hihi', status.HTTP_404_NOT_FOUND),
    ],
    ids=['success', 'text', 'hyphen', 'subpath', 'unexisting_id', 'excess_query'],
)
def test_retrieve_diff_id(dbsession, client, base_rentses_url, session_id, right_status_code):
    """Проверка получения сессии по разным URL-path."""
    try:
        id = RentalSession.query(session=dbsession).all()[session_id].id
    except (IndexError, TypeError):
        id = session_id
    response = client.get(f'{base_rentses_url}/{id}')
    assert response.status_code == right_status_code


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
            status.HTTP_200_OK,
            True,
        ),
        (
            {"end_ts": "2025-04-18T23:32:30.589Z", "actual_return_ts": "2025-04-18T23:32:30.589Z", "admin_close_id": 0},
            status.HTTP_200_OK,
            True,
        ),
        (
            {"status": "reserved", "actual_return_ts": "2025-04-18T23:32:30.589Z", "admin_close_id": 0},
            status.HTTP_200_OK,
            True,
        ),
        (
            {"status": "reserved", "end_ts": "2025-04-18T23:32:30.589Z", "admin_close_id": 0},
            status.HTTP_200_OK,
            True,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
            },
            status.HTTP_200_OK,
            True,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
                "admin_close_id": 0,
                "extra": "oops!",
            },
            status.HTTP_200_OK,
            True,
        ),
        (
            {
                "status": "cringe",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
                "admin_close_id": 0,
            },
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            False,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "he-he",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
                "admin_close_id": 0,
            },
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            False,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "ha-ha",
                "admin_close_id": 0,
            },
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            False,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": "2025-04-18T23:32:30.589Z",
                "admin_close_id": "boba",
            },
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            False,
        ),
        (
            {},
            status.HTTP_409_CONFLICT,
            False,
        ),
        (
            {"status": "reserved", "end_ts": None, "actual_return_ts": None, "admin_close_id": None},
            status.HTTP_409_CONFLICT,
            False,
        ),
        (
            {
                "status": "reserved",
                "end_ts": "2025-04-18T23:32:30.589Z",
                "actual_return_ts": None,
                "admin_close_id": None,
            },
            status.HTTP_200_OK,
            True,
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
def test_update_payload(dbsession, rentses, client, base_rentses_url, payload, right_status_code, update_in_db):
    """Проверка поведения при разном теле запроса."""
    old_model_fields = model_to_dict(rentses)
    response = client.patch(f"{base_rentses_url}/{rentses.id}", json=payload)
    print(f'В начале{model_to_dict(rentses)}')
    if response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        pytest.xfail(reason='Ждут issue #39. Удалить маркер, когда баг будет устранен.')
    assert response.status_code == right_status_code
    dbsession.refresh(rentses)
    print(f'В конце {model_to_dict(rentses)}')
    new_model_fields = model_to_dict(rentses)
    is_really_updated = old_model_fields != new_model_fields
    assert False
    assert is_really_updated == update_in_db


@pytest.mark.usefixtures('dbsession', 'rentses')
@pytest.mark.parametrize(
    'session_id, right_status_code',
    [
        ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('he-he/hoho', status.HTTP_404_NOT_FOUND),
        (-1, status.HTTP_404_NOT_FOUND),
        ('', status.HTTP_405_METHOD_NOT_ALLOWED),
        ('-1?hoho=hihi', status.HTTP_404_NOT_FOUND),
    ],
    ids=['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty', 'excess_query'],
)
def test_update_invalid_id(client, base_rentses_url, session_id, right_status_code):
    """Проверка обновления сессии по невалидному URL-path."""
    valid_update_payload = {
        "status": "reserved",
        "end_ts": "2025-04-18T23:32:30.589Z",
        "actual_return_ts": "2025-04-18T23:32:30.589Z",
        "admin_close_id": 0,
    }
    response = client.patch(f'{base_rentses_url}/{session_id}', json=valid_update_payload)
    assert response.status_code == right_status_code


# Tests for GET /rental-sessions
@pytest.mark.usefixtures('dbsession', 'rentses')
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
def test_get_url_query(
    client,
    base_rentses_url,
    is_reserved,
    is_canceled,
    is_dismissed,
    is_overdue,
    is_returned,
    is_active,
    right_status_code,
):
    """Проверка получения сессий при разных URL-query."""
    query_data = {
        key: value
        for key, value in {
            'is_reserved': is_reserved,
            'is_canceled': is_canceled,
            'is_dismissed': is_dismissed,
            'is_overdue': is_overdue,
            'is_returned': is_returned,
            'is_active': is_active,
        }.items()
        if value is not None
    }
    response = client.get(f'{base_rentses_url}', params=query_data)
    assert response.status_code == right_status_code
    if right_status_code == status.HTTP_200_OK:
        assert isinstance(response.json(), list)


def test_get_query_extra_param(dbsession, client, base_rentses_url, rentses):
    """Проверка запроса с непредусмотренным параметром в URL-query."""
    extra_response = client.get(f'{base_rentses_url}?hehe=True')
    assert extra_response.status_code == status.HTTP_200_OK
    valid_response = client.get(f'{base_rentses_url}')
    assert len(extra_response.json()) == len(
        valid_response.json()
    ), 'Убедитесь, что экстра параметр не меняет поведения хэндлера!'


# Tests for DELETE /rental-sessions/{session_id}/cancel
def test_cancel_success(dbsession, client, base_rentses_url, rentses):
    """Проверяет успешный сценарий отмены аренды."""
    with (
        check_object_update(rentses, dbsession, status=RentStatus.CANCELED),
        check_object_update(Item.get(id=rentses.item_id, session=dbsession), dbsession, is_available=True),
    ):
        response = client.delete(f'{base_rentses_url}/{rentses.id}/cancel')
        assert response.status_code == status.HTTP_200_OK, 'Убедитесь, что аренду можно отменить!'


@pytest.mark.parametrize(
    'session_id, right_status_code',
    [
        ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('he-he/hoho', status.HTTP_404_NOT_FOUND),
        (-1, status.HTTP_404_NOT_FOUND),
        ('', status.HTTP_404_NOT_FOUND),
        ('-1?hoho=hihi', status.HTTP_405_METHOD_NOT_ALLOWED),
    ],
    ids=['text', 'hyphen', 'trailing_slash', 'negative_num', 'empty', 'excess_query'],
)
def test_cancel_invalid(client, base_rentses_url, session_id, right_status_code):
    """Проверяет случай запроса по невалидному session_id."""
    response = client.delete(f'{base_rentses_url}/{session_id}/cancel')
    assert response.status_code == right_status_code


def test_cancel_wrong_user(dbsession, rentses, base_rentses_url, another_client):
    """Проверяет случай запроса от пользователя, который не привязан к данной сессии."""
    with check_object_update(rentses, dbsession, status=rentses.status):
        response = another_client.delete(f'{base_rentses_url}/{rentses.id}/cancel')
        assert (
            response.status_code == status.HTTP_403_FORBIDDEN
        ), 'Убедитесь, что не создатель аренды не может ее отменить!'


@pytest.mark.parametrize(
    'new_wrong_status',
    [RentStatus.ACTIVE, RentStatus.CANCELED, RentStatus.OVERDUE, RentStatus.RETURNED, RentStatus.DISMISSED],
    ids=['active', 'canceled', 'overdue', 'returned', 'dismissed'],
)
def test_cancel_wrong_status(dbsession, client, base_rentses_url, rentses, new_wrong_status):
    """Проверяет случай запроса на отмену незарезервированной сессии."""
    RentalSession.update(id=rentses.id, session=dbsession, status=new_wrong_status)
    dbsession.commit()
    dbsession.refresh(rentses)
    with check_object_update(rentses, dbsession, status=new_wrong_status):
        response = client.delete(f'{base_rentses_url}/{rentses.id}/cancel')
        assert (
            response.status_code == status.HTTP_403_FORBIDDEN
        ), 'Убедитесь, что нельзя отменить незарезервированную сессию!'
