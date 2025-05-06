import logging

import pytest
from starlette import status

from rental_backend.models import Item
from rental_backend.settings import get_settings


logger = logging.getLogger(__name__)
url: str = '/item'

settings = get_settings()


@pytest.mark.parametrize('response_status', [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND])
def test_create_item(client, item_type_fixture, response_status):
    if response_status == status.HTTP_200_OK:
        body = {"type_id": item_type_fixture.id, "is_available": True}
    # check non-existing type_id request
    elif response_status == status.HTTP_404_NOT_FOUND:
        body = {"type_id": item_type_fixture.id - 1, "is_available": True}
    post_response = client.post(url, json=body)
    assert post_response.status_code == response_status


@pytest.mark.parametrize(
    'item_n,response_status',
    [(0, status.HTTP_200_OK), (1, status.HTTP_200_OK), (2, status.HTTP_404_NOT_FOUND)],
)
def test_get_item_id(client, dbsession, items_with_types, item_n, response_status):
    items = items_with_types
    item = dbsession.query(Item).filter(Item.id == items[item_n].id).one_or_none()
    # check non-existing id request
    item_id = -1
    if item.is_available:
        item_id = item.id
    response = client.get(f'{url}/{item_id}')
    assert response.status_code == response_status


@pytest.mark.parametrize(
    'params,response_status',
    [
        ({"type_id": 0}, status.HTTP_200_OK),
    ],
)
def test_get_items_by_type_id(client, params, response_status):
    response = client.get(f'{url}', params=params)
    assert response.status_code == response_status
    if response_status == status.HTTP_200_OK:
        json_response = response.json()
        assert json_response!=""
