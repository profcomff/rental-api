from typing import Dict, Any

import pytest
from fastapi.testclient import TestClient
from starlette import status
from sqlalchemy import desc

from rental_backend.__main__ import app
from rental_backend.models.db import Item, ItemType
from rental_backend.models.base import BaseDbModel
from rental_backend.routes.item import item
from rental_backend.schemas.base import StatusResponseModel
from rental_backend.schemas.models import ItemGet, ItemPost


client = TestClient(app)
url = '/item'


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
    return '?' + '?'.join(f'{k}={data[k]}' for k in data)


@pytest.fixture
def base_item_url(client: TestClient) -> str:
    """Формирует корневой URL для Item."""
    return f'{client.base_url}{item.prefix}'


@pytest.fixture
def mock_item():
    return {
        "id": 1,
        "name": "Test Item",
        "description": "This is a test item",
        "type_id": 1,
        "is_available": True,
    }


@pytest.fixture
def mock_item_type():
    return {
        "id": 1,
        "name": "Test Type",
    }


# Тесты для функции get_items
def test_get_items_success(mock_item):
    response = client.get(f"{url}/item")
    assert response.status_code == status.HTTP_200_OK
    assert isinstance(response.json(), list)


def test_get_items_with_type_id(mock_item, mock_item_type):
    response = client.get(f"{url}/item?type_id=1")
    assert response.status_code == status.HTTP_200_OK
    assert all(item['type_id'] == 1 for item in response.json())


def test_get_items_empty_list():
    response = client.get(f"{url}/item")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


def test_get_items_invalid_type_id():
    response = client.get(f"{url}/item?type_id=999")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


def test_get_items_unauthorized():
    response = client.get(f"{url}/item", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_items_internal_server_error(monkeypatch):
    def mock_db_error():
        raise Exception("Database error")

    monkeypatch.setattr("rental_backend.models.db.Item.query", mock_db_error)
    response = client.get(f"{url}/item")
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_get_items_with_pagination():
    response = client.get(f"{url}/item?skip=0&limit=10")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) <= 10


# Тесты для функции create_item
def test_create_item_success(mock_item_type):
    item_data = {
        "name": "New Item",
        "description": "New Description",
        "type_id": 1,
    }
    response = client.post(f"{url}/item", json=item_data)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "New Item"


def test_create_item_invalid_type_id():
    item_data = {
        "name": "New Item",
        "description": "New Description",
        "type_id": 999,
    }
    response = client.post(f"{url}/item", json=item_data)
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_create_item_missing_fields():
    item_data = {
        "name": "New Item",
    }
    response = client.post(f"{url}/item", json=item_data)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_item_unauthorized():
    item_data = {
        "name": "New Item",
        "description": "New Description",
        "type_id": 1,
    }
    response = client.post(f"{url}/item", json=item_data, headers={"Authorization": "Bearer invalid"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_create_item_internal_server_error(monkeypatch):
    def mock_db_error():
        raise Exception("Database error")

    monkeypatch.setattr("rental_backend.models.db.Item.create", mock_db_error)
    item_data = {
        "name": "New Item",
        "description": "New Description",
        "type_id": 1,
    }
    response = client.post(f"{url}/item", json=item_data)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_create_item_duplicate_name(mock_item):
    item_data = {
        "name": "Test Item",
        "description": "Duplicate Item",
        "type_id": 1,
    }
    response = client.post(f"{url}/item", json=item_data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_create_item_with_empty_name():
    item_data = {
        "name": "",
        "description": "Empty Name Item",
        "type_id": 1,
    }
    response = client.post(f"{url}/item", json=item_data)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# Тесты для функции update_item
@pytest.mark.parametrize(
        'data, right_status_code',
        [
            ({"is_available": True,}, status.HTTP_200_OK),
            ({"is_available": 'invalid'}, status.HTTP_422_UNPROCESSABLE_ENTITY),
            ({}, {'set_old': status.HTTP_409_CONFLICT, 'set_new': status.HTTP_200_OK}),
            ({"is_available": False,}, status.HTTP_409_CONFLICT),
        ],
        ids=['valid_new_data', 'invalid_new_data', 'empty_data', 'old_data',]
)
def test_query_for_update_item(item_fixture, client, dbsession, base_item_url, data, right_status_code):
    """Проверка реакции ручки PATCH /items на разные входные данные."""
    old_model_fields = model_to_dict(item_fixture)
    response = client.patch(f"{base_item_url}/{item_fixture.id}{make_url_query(data)}")
    if isinstance(right_status_code, dict):
        dbsession.refresh(item_fixture)
        new_model_fields = model_to_dict(item_fixture)
        if new_model_fields == old_model_fields:
            assert response.status_code == right_status_code['set_old']
        else:
            assert response.status_code == right_status_code['set_new']
    else:
        assert response.status_code == right_status_code


@pytest.mark.parametrize(
        'data, is_updated',
        [
            ({"is_available": True,}, True),
            ({"is_available": 'invalid'}, False),
            ({}, {status.HTTP_409_CONFLICT: False, status.HTTP_200_OK: True}),
            ({"is_available": False,}, False),
        ],
        ids=['valid_new_data', 'invalid_new_data', 'empty_data', 'old_data',]
)
def test_update_item_model(item_fixture, client, base_item_url, dbsession, data, is_updated):
    """Проверка наличия изменений в БД после отработки ручки PATCH /items"""
    old_model_fields = model_to_dict(item_fixture)
    response = client.patch(f"{base_item_url}/{item_fixture.id}{make_url_query(data)}")
    dbsession.refresh(item_fixture)
    new_model_fields = model_to_dict(item_fixture)
    if isinstance(is_updated, dict):
        assert (old_model_fields != new_model_fields) == is_updated[response.status_code]
    else:
        is_really_changed = old_model_fields != new_model_fields
        assert is_really_changed == is_updated


def test_update_item_not_found(client, dbsession, base_item_url):
    """Пробует обновить несуществующий Item.
    
    .. caution::
        Несуществующий id осуществляется без учета id 'soft deleted' Item.
        Поэтому возможны ошибки при изменении поведения Item.query().
    """
    try:
        unexisting_id = Item.query(session=dbsession).order_by(desc('id'))[0].id + 1
    except IndexError:
        unexisting_id = 1
    query_params = make_url_query({'is_available': True})
    response = client.patch(f"{base_item_url}/{unexisting_id}{query_params}")
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_update_item_unauthorized():
    update_data = {
        "is_available": False,
    }
    response = client.patch(f"{url}/item/1", json=update_data, headers={"Authorization": "Bearer invalid"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_update_item_internal_server_error(monkeypatch):
    def mock_db_error():
        raise Exception("Database error")

    monkeypatch.setattr("rental_backend.models.db.Item.query", mock_db_error)
    update_data = {
        "is_available": False,
    }
    response = client.patch(f"{url}/item/1", json=update_data)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# Тесты для функции delete_item
def test_delete_item_success(mock_item):
    response = client.delete(f"{url}/item/1")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "success"


def test_delete_item_not_found():
    response = client.delete(f"{url}/item/999")
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_item_unauthorized():
    response = client.delete(f"{url}/item/1", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_delete_item_internal_server_error(monkeypatch):
    def mock_db_error():
        raise Exception("Database error")

    monkeypatch.setattr("rental_backend.models.db.Item.delete", mock_db_error)
    response = client.delete(f"{url}/item/1")
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_delete_item_with_invalid_id():
    response = client.delete(f"{url}/item/invalid")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_delete_item_without_required_scope(mock_item):
    response = client.delete(f"{url}/item/1")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_delete_item_already_deleted(mock_item):
    client.delete(f"{url}/item/1")
    response = client.delete(f"{url}/item/1")
    assert response.status_code == status.HTTP_404_NOT_FOUND
