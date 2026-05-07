import logging

import pytest
from starlette import status

from rental_backend.models import Item
from rental_backend.settings import get_settings


logger = logging.getLogger(__name__)
url: str = '/item'

settings = get_settings()


@pytest.mark.parametrize(
    'item_n,response_status,availability',
    [
        (0, status.HTTP_200_OK, True),
        (0, status.HTTP_200_OK, True),
        (1, status.HTTP_200_OK, False),
        (1, status.HTTP_422_UNPROCESSABLE_ENTITY, 'abc'),
        (2, status.HTTP_404_NOT_FOUND, True),
    ],
)
def test_create_item(client, item_type_fixture, item_n, response_status, availability):
    item_id = -1
    if item_n < len(item_type_fixture):
        item_id = item_type_fixture[item_n].id
    body = {"type_id": item_id, "is_available": availability}
    post_response = client.post(url, json=body)
    assert post_response.status_code == response_status


@pytest.mark.parametrize(
    'item_n,response_status',
    [(0, status.HTTP_200_OK), (1, status.HTTP_200_OK), (2, status.HTTP_404_NOT_FOUND)],
)
def test_get_item_id(client, dbsession, items_with_types, item_n, response_status):
    item = dbsession.query(Item).filter(Item.id == items_with_types[item_n].id).one_or_none()
    # check non-existing id request
    item_id = -1
    if item.is_available:
        item_id = item.id
    response = client.get(f'{url}/{item_id}')
    assert response.status_code == response_status


@pytest.mark.parametrize(
    'item_n,response_status',
    [(0, status.HTTP_200_OK), (1, status.HTTP_200_OK)],
)
def test_get_items_by_type_id(client, items_with_types, item_n, response_status):
    query = {"type_id": f'{items_with_types[item_n].type_id}'}
    response = client.get(f'{url}', params=query)
    assert response.status_code == response_status


@pytest.mark.parametrize(
    "item_n, order_by, order, is_available, response_status",
    [
        (0, None, None, True, status.HTTP_200_OK),
        (0, "id", None, True, status.HTTP_200_OK),
        (0, "type_id", "asc", False, status.HTTP_200_OK),
        (0, "is_available", "desc", False, status.HTTP_200_OK),
        (0, None, None, False, status.HTTP_200_OK),
        (1, "id", "asc", False, status.HTTP_200_OK),
        (1, "type_id", "desc", True, status.HTTP_200_OK),
        (1, "is_available", None, True, status.HTTP_200_OK),
        (1, None, "asc", True, status.HTTP_200_OK),
        (0, "id", "desc", True, status.HTTP_200_OK),
        (1, "type_id", None, False, status.HTTP_200_OK),
        (0, "is_available", "asc", False, status.HTTP_200_OK),
        (0, None, "desc", False, status.HTTP_200_OK),
        (None, "id", None, True, status.HTTP_200_OK),
        (None, "type_id", "asc", False, status.HTTP_200_OK),
        (None, "is_available", "desc", False, status.HTTP_200_OK),
        (None, "is_available", "desc", False, status.HTTP_200_OK),
    ],
)
def test_get_items_positive_cases(client, items_with_types, item_n, order_by, order, is_available, response_status):
    dict_of_params = {
        "type_id": items_with_types[item_n].type_id if item_n is not None else None,
        "order_by": order_by,
        "order": order,
        "is_availible": str(is_available).lower() if is_available is not None else None,
    }
    query = {k: v for k, v in dict_of_params.items() if v is not None}
    response = client.get(url, params=query)
    assert response.status_code == response_status
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for item in data:
        assert "id" in item
        assert "type_id" in item


@pytest.mark.parametrize(
    "item_n, order_by, order, response_status",
    [
        (None, None, "desc", status.HTTP_200_OK),
        (0, None, "desc", status.HTTP_200_OK),
    ],
)
def test_get_items_check_desc_order_by_id(client, items_with_different_types, item_n, order_by, order, response_status):
    dict_of_params = {
        "type_id": items_with_different_types[item_n].type_id if item_n is not None else None,
        "order_by": order_by,
        "order": order,
    }
    query = {k: v for k, v in dict_of_params.items() if v is not None}
    response = client.get(url, params=query)
    assert response.status_code == response_status

    data = response.json()

    key = lambda x: x["id"]
    compare = lambda x, y: x >= y
    assert all(compare(key(x), key(y)) for x, y in zip(data, data[1:])) is True


@pytest.mark.parametrize(
    "item_n, order_by, order, response_status",
    [
        (None, "type_id", "desc", status.HTTP_200_OK),
        (1, "type_id", "desc", status.HTTP_200_OK),
    ],
)
def test_get_items_check_desc_order_by_type_id(
    client, items_with_different_types, item_n, order_by, order, response_status
):
    dict_of_params = {
        "type_id": items_with_different_types[item_n].type_id if item_n is not None else None,
        "order_by": order_by,
        "order": order,
    }
    query = {k: v for k, v in dict_of_params.items() if v is not None}
    response = client.get(url, params=query)
    assert response.status_code == response_status

    data = response.json()

    key = lambda x: x["type_id"]
    compare = lambda x, y: x >= y
    assert all(compare(key(x), key(y)) for x, y in zip(data, data[1:])) is True


@pytest.mark.parametrize(
    "item_n, order_by, order, response_status",
    [
        (None, "is_available", "desc", status.HTTP_200_OK),
        (1, "is_available", "desc", status.HTTP_200_OK),
    ],
)
def test_get_items_check_desc_order_by_is_available(
    client, items_with_different_types, item_n, order_by, order, response_status
):
    dict_of_params = {
        "type_id": items_with_different_types[item_n].type_id if item_n is not None else None,
        "order_by": order_by,
        "order": order,
    }
    query = {k: v for k, v in dict_of_params.items() if v is not None}
    response = client.get(url, params=query)
    assert response.status_code == response_status

    data = response.json()

    key = lambda x: x["is_available"]
    compare = lambda x, y: x >= y
    assert all(compare(key(x), key(y)) for x, y in zip(data, data[1:])) is True


@pytest.mark.parametrize(
    'item_n,body,response_status',
    [
        # conflict with available true as it is true before update
        (0, {"is_available": True}, status.HTTP_409_CONFLICT),
        (1, {"is_available": False}, status.HTTP_200_OK),
        (2, {"is_available": True}, status.HTTP_200_OK),
        # Non-existent id
        (3, {"is_available": False}, status.HTTP_404_NOT_FOUND),
    ],
)
def test_update_item(client, items_with_types, item_n, body, response_status):
    item_id = -1
    if item_n < len(items_with_types):
        item_id = items_with_types[item_n].id
    response = client.patch(f"{url}/{item_id}", params=body)
    assert response.status_code == response_status
    if response.status_code == status.HTTP_200_OK:
        json_response = response.json()
        assert json_response["id"] == items_with_types[item_n].id
        assert json_response["type_id"] == items_with_types[item_n].type_id
        assert json_response["is_available"] != items_with_types[item_n].is_available


def test_delete_item(client, items_with_types):
    items = items_with_types
    response = client.delete(f"{url}/{items[0].id}")
    assert response.status_code == status.HTTP_200_OK
    # trying to delete deleted
    response = client.delete(f"{url}/{items[0].id}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    # trying to get deleted
    response = client.get(f'{url}/{items[0].id}')
    assert response.status_code == status.HTTP_404_NOT_FOUND
