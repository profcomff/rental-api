import logging

import pytest
from starlette import status

from rental_backend.settings import get_settings


logger = logging.getLogger(__name__)
url: str = '/itemtype'

settings = get_settings()


@pytest.mark.parametrize(
    'item_n,response_status',
    [
        (0, status.HTTP_200_OK),
        (1, status.HTTP_200_OK),
        (2, status.HTTP_422_UNPROCESSABLE_ENTITY),
    ],
)
def test_create_item_type(client, item_type_fixture, item_n, response_status):
    body = None
    if item_n < len(item_type_fixture):
        body = {"name": item_type_fixture[item_n].name}
    post_response = client.post(url, json=body)
    assert post_response.status_code == response_status


def test_get_item_type(client, item_type_fixture):
    # 200_OK as any item types are found
    get_response = client.get(url)
    assert get_response.status_code == status.HTTP_200_OK
    response = client.delete(f"{url}/{item_type_fixture[0].id}")
    assert response.status_code == status.HTTP_200_OK
    response = client.delete(f"{url}/{item_type_fixture[1].id}")
    assert response.status_code == status.HTTP_200_OK
    # 404_NOT_FOUND as no item types are found
    get_response = client.get(url)
    assert get_response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize(
    'item_n,response_status',
    [
        (0, status.HTTP_200_OK),
        (1, status.HTTP_200_OK),
        (2, status.HTTP_404_NOT_FOUND),
    ],
)
def test_get_item_type_id(client, item_n, item_type_fixture, response_status):
    type_id = -1
    if item_n < len(item_type_fixture):
        type_id = item_type_fixture[item_n].id
    response = client.get(f'{url}/{type_id}')
    assert response.status_code == response_status


@pytest.mark.parametrize(
    'item_n,body,response_status',
    [
        (0, {"name": True}, status.HTTP_422_UNPROCESSABLE_ENTITY),
        (1, {"name": "TestOK"}, status.HTTP_200_OK),
        # Non-existent id
        (2, {"name": "TestBAD"}, status.HTTP_404_NOT_FOUND),
    ],
)
def test_update_item_type(client, dbsession, item_n, body, item_type_fixture, response_status):
    item_type_id = -1
    if item_n < len(item_type_fixture):
        item_type_id = item_type_fixture[item_n].id
    response = client.patch(f"{url}/{item_type_id}", json=body)
    assert response.status_code == response_status
    if response.status_code == status.HTTP_200_OK:
        json_response = response.json()
        assert json_response["id"] == item_type_fixture[item_n].id
        assert json_response["name"] == body["name"]


@pytest.mark.parametrize(
    'item_n,response_status',
    [
        # Есть один item available
        (0, status.HTTP_200_OK),
        # type_id без items
        (1, status.HTTP_404_NOT_FOUND),
        # Несуществующий type_id
        (2, status.HTTP_404_NOT_FOUND),
    ],
)
def test_update_item_type_available(client, item_n, items_with_same_type_id, response_status):
    type_id = -100000
    if item_n < len(items_with_same_type_id):
        type_id = items_with_same_type_id[item_n].id
    response = client.patch(f"{url}/available/{type_id}")
    assert response.status_code == response_status
    if response.status_code == status.HTTP_200_OK:
        response = client.patch(f"{url}/available/{type_id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_item_type(client, item_type_fixture):
    response = client.delete(f"{url}/{item_type_fixture[0].id}")
    assert response.status_code == status.HTTP_200_OK
    # checking if items are not deleted
    assert item_type_fixture[0].items == []
    # trying to delete deleted
    response = client.delete(f"{url}/{item_type_fixture[0].id}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    # trying to get deleted
    response = client.get(f'{url}/{item_type_fixture[0].id}')
    assert response.status_code == status.HTTP_404_NOT_FOUND
