import pytest
from fastapi.testclient import TestClient
from starlette import status

from rental_backend.__main__ import app


client = TestClient(app)
url = '/item'


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
def test_update_item_success(mock_item):
    update_data = {
        "is_available": False,
    }
    response = client.patch(f"{url}/item/1", json=update_data)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["is_available"] == False


def test_update_item_not_found():
    update_data = {
        "is_available": False,
    }
    response = client.patch(f"{url}/item/999", json=update_data)
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


def test_update_item_with_invalid_data():
    update_data = {
        "is_available": "invalid",
    }
    response = client.patch(f"{url}/item/1", json=update_data)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_update_item_with_no_changes(mock_item):
    update_data = {
        "is_available": True,
    }
    response = client.patch(f"{url}/item/1", json=update_data)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["is_available"] == True


def test_update_item_with_empty_data():
    response = client.patch(f"{url}/item/1", json={})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


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
