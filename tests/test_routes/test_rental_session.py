import datetime
from contextlib import contextmanager
from typing import Generator
import pytest
from sqlalchemy import desc
from starlette import status

from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from rental_backend.routes import app

from rental_backend.models.base import BaseDbModel
from rental_backend.models.db import Item, ItemType, RentalSession, Strike
from rental_backend.routes.rental_session import rental_session
from rental_backend.routes.rental_session import RENTAL_SESSION_EXPIRY
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
@pytest.mark.usefixtures(
    'expire_mock'
)  # подменяет check_sessions_expiration чтобы не выполнялась реальная проверка просроченных сессий
@pytest.mark.parametrize(
    'start_item_avail, end_item_avail, itemtype_list_ind, right_status_code, num_of_creations',
    [
        (True, False, 0, status.HTTP_200_OK, 1),
        (False, False, 0, status.HTTP_404_NOT_FOUND, 0),
        (True, True, 1, status.HTTP_404_NOT_FOUND, 0),  # результат зависит от типа создаваемого предмета в item_fixture
        (True, True, 2, status.HTTP_404_NOT_FOUND, 0),
    ],
    ids=['avail_item', 'not_avail_item', 'existing_type_no_items', 'unexisting_itemtype'],
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
    ###
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


@pytest.mark.parametrize(
    "blocking_status",
    [RentStatus.RESERVED, RentStatus.ACTIVE, RentStatus.OVERDUE],
    ids=["reserved", "active", "overdue"],
)
def test_create_with_existing_blocking_session(
    dbsession, client, base_rentses_url, items_with_same_type_id, authlib_user, blocking_status
):
    """
    Проверяет, что нельзя создать новую сессию для типа, если у пользователя уже есть
    сессия в статусе RESERVED/ACTIVE/OVERDUE для этого типа.
    """
    # Фикстура items_with_same_type_id возвращает список item_types,
    # где первый тип содержит два предмета: items[0] is_available=True, items[1] is_available=False.
    item_type = items_with_same_type_id[0]
    items = item_type.items
    assert len(items) >= 2, "Для теста нужно минимум два предмета одного типа"
    # Делаем второй предмет доступным (если он был недоступен)
    items[1].is_available = True
    dbsession.add(items[1])
    dbsession.commit()
    # Создаём блокирующую сессию для первого предмета
    now = datetime.datetime.now(datetime.timezone.utc)
    blocking_session = RentalSession.create(
        session=dbsession,
        user_id=authlib_user["id"],
        item_id=items[0].id,
        status=blocking_status,
        reservation_ts=now,
    )
    items[0].is_available = False
    dbsession.add(blocking_session, items[0])
    dbsession.commit()
    try:
        # Пытаемся создать новую сессию для того же типа
        response = client.post(f"{base_rentses_url}/{item_type.id}")
        # Ожидаем конфликт, так как блокирующая сессия существует
        assert response.status_code == status.HTTP_409_CONFLICT
    finally:
        # Гарантированный откат транзакции для предотвращения PendingRollbackError (если она была помечена как требующая отката из-за предыдущего исключения)
        dbsession.rollback()


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
        assert response.status_code == right_status_code


@pytest.mark.usefixtures('expiration_time_mock')
def test_create_and_expire(dbsession, client, base_rentses_url, item_fixture):
    """
    Проверяет, что просроченная сессия (RESERVED) переходит в EXPIRED при следующем вызове check_sessions_expiration.
    """
    item_fixture.is_available = True
    dbsession.add(item_fixture)
    dbsession.commit()
    # Создаём сессию аренды
    response = client.post(f'{base_rentses_url}/{item_fixture.type_id}')
    assert response.status_code == status.HTTP_200_OK
    session_id = response.json()['id']
    # Проверяем, что сразу после создания статус RESERVED (корректно)
    session = RentalSession.get(id=session_id, session=dbsession)
    assert session.status == RentStatus.RESERVED
    # Искусственно сдвигаем время резервации в прошлое, чтобы условие expiry выполнилось немедленно.
    # RENTAL_SESSION_EXPIRY подменён фикстурой expiration_time_mock на 2 секунды.
    new_reservation_ts = (
        datetime.datetime.now(datetime.timezone.utc) - RENTAL_SESSION_EXPIRY - datetime.timedelta(seconds=1)
    )
    session.reservation_ts = new_reservation_ts
    dbsession.add(session)
    dbsession.commit()
    # Вызываем любой эндпоинт, который включает check_sessions_expiration, чтобы просроченные сессии были обработаны и обновлены в БД.
    # Например, GET /rental-sessions/{session_id} (тоже имеет эту зависимость)
    response = client.get(f'{base_rentses_url}/{session_id}')
    assert response.status_code == status.HTTP_200_OK
    # Обновляем объект сессии из БД и проверяем статус
    dbsession.refresh(session)
    assert (
        session.status == RentStatus.EXPIRED
    ), f"Статус сессии аренды должен стать EXPIRED, но остался {session.status}"


# Тест на начало уже активной сессии
def test_start_already_active_session(dbsession, client, base_rentses_url, active_rentses):
    """Проверка, что нельзя начать уже активную сессию."""
    response = client.patch(f'{base_rentses_url}/{active_rentses.id}/start')
    assert response.status_code == status.HTTP_403_FORBIDDEN


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
        'strike_no_reason',
        'only_reason_no_strike',
        'invalid_with_num',
        'invalid_with_text',
        'invalid_with_trailing_slash',
    ],
)
def test_return_with_strike(
    dbsession, client, base_rentses_url, active_rentses, with_strike, strike_reason, right_status_code, strike_created
):
    """Проверяет завершение аренды со страйком, статус сессии, доступность предмета и атрибуты страйка."""
    query_dict = dict()
    if with_strike is not None:
        query_dict['with_strike'] = with_strike
    if strike_reason is not None:
        query_dict['strike_reason'] = strike_reason
    num_of_creations = 1 if strike_created else 0
    session_id = active_rentses.id
    item_id = active_rentses.item_id
    with check_object_creation(Strike, dbsession, num_of_creations):
        response = client.patch(f'{base_rentses_url}/{active_rentses.id}/return', params=query_dict)
        assert response.status_code == right_status_code
        # Если статус ответа 200, проверяем изменения в БД
        if right_status_code == status.HTTP_200_OK:
            dbsession.refresh(active_rentses)
            assert active_rentses.status == RentStatus.RETURNED, "Статус сессии должен стать RETURNED"
            assert active_rentses.item.is_available is True, "Предмет должен стать доступным"
            # Проверяем создание страйка
            if strike_created:
                strike = dbsession.query(Strike).filter(Strike.session_id == session_id).first()
                assert strike is not None, "Страйк должен быть создан"
                assert strike.user_id == active_rentses.user_id, "user_id страйка не совпадает"
                # admin_id должен быть ID текущего пользователя (из фикстуры client, которая использует user_mock с id=0)
                assert strike.admin_id == 0, "admin_id страйка должен быть ID администратора"
                expected_reason = strike_reason if strike_reason is not None else ""
                assert strike.reason == expected_reason, "Причина страйка не совпадает"
                assert strike.session_id == session_id, "session_id страйка не совпадает"
            else:
                # Если страйк не должен быть создан, убеждаемся, что его нет
                strike = dbsession.query(Strike).filter(Strike.session_id == session_id).first()
                assert strike is None, "Страйк не должен быть создан"
        else:
            # Для невалидных запросов проверяем, что состояние не изменилось
            dbsession.refresh(active_rentses)
            assert active_rentses.status == RentStatus.ACTIVE, "Статус сессии не должен измениться"
            assert active_rentses.item.is_available is False, "Предмет должен остаться недоступным"
            # Страйков быть не должно
            strike = dbsession.query(Strike).filter(Strike.session_id == session_id).first()
            assert strike is None, "Страйк не должен быть создан при ошибке"


def test_return_with_set_end_ts(dbsession, client, base_rentses_url, active_rentses):
    """Проверяет, что при обновлении RentalSession с end_ts не None сохраняется именно существующий, а не создается новый."""
    active_rentses.end_ts = datetime.datetime.now(tz=datetime.timezone.utc)
    dbsession.add(active_rentses)
    dbsession.commit()
    with check_object_update(active_rentses, dbsession, end_ts=active_rentses.end_ts):
        response = client.patch(f'{base_rentses_url}/{active_rentses.id}/return')
        assert response.status_code == status.HTTP_200_OK


# Tests for GET /rental-sessions/{session_id}
@pytest.mark.usefixtures('rentses')
@pytest.mark.parametrize(
    'session_id, right_status_code',
    [
        (0, status.HTTP_200_OK),
        (1, status.HTTP_404_NOT_FOUND),  # rentses создает только одну сессию
        ('hihi', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('ha-ha', status.HTTP_422_UNPROCESSABLE_ENTITY),
        ('he-he/hoho', status.HTTP_404_NOT_FOUND),
        (-2, status.HTTP_404_NOT_FOUND),
        ('-1?hoho=hihi', status.HTTP_404_NOT_FOUND),
    ],
    ids=['success', 'no_such_session_in_rentses', 'text', 'hyphen', 'subpath', 'unexisting_id', 'excess_query'],
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
    assert response.status_code == right_status_code
    dbsession.refresh(rentses)
    new_model_fields = model_to_dict(rentses)
    is_really_updated = old_model_fields != new_model_fields
    assert is_really_updated == update_in_db


def test_regular_user_cannot_update_rental_session(dbsession, client, rentses, another_authlib_user):
    """
    Проверка, что обычный пользователь (не админ) не может обновить сессию.
    Ожидается 403 Forbidden, данные в БД не должны измениться.
    """

    def mock_unionauth_call(self, request):
        required_scopes = set(self.scopes or [])
        user_scopes = set(another_authlib_user.get('scopes', []))
        if required_scopes and not required_scopes.issubset(user_scopes):
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return another_authlib_user

    with patch('auth_lib.fastapi.UnionAuth.__call__', new=mock_unionauth_call):
        old_end_ts = rentses.end_ts
        payload = {"end_ts": "2026-12-31T23:59:59.000Z"}

        response = client.patch(f"/rental-sessions/{rentses.id}", json=payload)

        assert response.status_code == status.HTTP_403_FORBIDDEN

        dbsession.refresh(rentses)
        assert rentses.end_ts == old_end_ts


def test_admin_can_update_any_rental_session(dbsession, client, another_rentses, authlib_user):
    """
    Проверка, что администратор может обновить сессию другого пользователя.
    Ожидается 200 OK, данные в БД должны измениться.
    """

    def mock_unionauth_call(self, request):
        # self — экземпляр UnionAuth, у которого есть атрибут scopes
        required_scopes = set(self.scopes or [])
        user_scopes = set(authlib_user.get('scopes', []))
        if required_scopes and not required_scopes.issubset(user_scopes):
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return authlib_user

    with patch('auth_lib.fastapi.UnionAuth.__call__', new=mock_unionauth_call):
        old_end_ts = another_rentses.end_ts
        payload = {"end_ts": "2026-12-31T23:59:59.000Z"}

        response = client.patch(f"/rental-sessions/{another_rentses.id}", json=payload)

        assert response.status_code == status.HTTP_200_OK

        dbsession.refresh(another_rentses)
        assert another_rentses.end_ts is not None
        assert another_rentses.end_ts != old_end_ts


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
        ('-1?hoho=hihi', status.HTTP_404_NOT_FOUND),  # HTTP_405_METHOD_NOT_ALLOWED
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
