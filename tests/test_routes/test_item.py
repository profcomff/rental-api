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
    query = {"item_type": f'{items_with_types[item_n].type_id}'}
    response = client.get(f'{url}', params=query)
    assert response.status_code == response_status


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
    try:
        item_id = items_with_types[item_n].id
    except IndexError:
        pass
    response = client.patch(f"{url}/{item_id}", params=body)
    assert response.status_code == response_status
    if response.status_code == status.HTTP_200_OK:
        json_responce = response.json()
        assert json_responce["id"] == items_with_types[item_n].id
        assert json_responce["type_id"] == items_with_types[item_n].type_id
        assert json_responce["is_available"] != items_with_types[item_n].is_available


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
