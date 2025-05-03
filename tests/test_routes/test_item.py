import logging

import pytest
from starlette import status
from rental_backend.settings import get_settings
from rental_backend.models import Item

logger = logging.getLogger(__name__)
url: str = '/item'

settings = get_settings()

@pytest.mark.parametrize('response_status', [status.HTTP_200_OK, status.HTTP_409_CONFLICT])
def test_create_item(client, dbsession, response_status):
    body = {"type_id": 1, "is_available": True}
    post_response = client.post(url, json=body)
    assert post_response.status_code == response_status
    # cleanup on a last run
    if response_status == status.HTTP_409_CONFLICT:
        item = dbsession.query(Item).filter(Item.id == 0).one_or_none()
        assert item is not None
        dbsession.delete(item)
        dbsession.commit()
        item = dbsession.query(Item).filter(Item.id == 0).one_or_none()
        assert item is None

"""
@pytest.mark.parametrize(
    'item_n,response_status',
    [
        (0, status.HTTP_200_OK),
        (1, status.HTTP_200_OK),
        (2, status.HTTP_200_OK),
        (3, status.HTTP_404_NOT_FOUND),
    ],
)
def test_get_item(client, dbsession, items, item_n, response_status):
    items_list = (
        dbsession.query(Item).filter(Item.type_id == items[item_n].type_id).one_or_none()
    )
    item_id = -1
    if items_list:
        item_id = items_list.id
    get_response = client.get(f'{url}/{item_id}')
    assert get_response.status_code == response_status
    if response_status == status.HTTP_200_OK:
        json_response = get_response.json()
        assert json_response["type_id"] is None

"""