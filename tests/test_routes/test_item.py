import logging

import pytest
from starlette import status
from rental_backend.settings import get_settings
from rental_backend.models import Item

logger = logging.getLogger(__name__)
url: str = '/item/item'

settings = get_settings()

@pytest.mark.parametrize('response_status', [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND])
def test_create_item(client, item_type_fixture, response_status):
    if response_status==status.HTTP_200_OK:
        body = {"id":1, "type_id": item_type_fixture.id, "is_available": True}
    #check non-existing type_id request
    elif response_status==status.HTTP_404_NOT_FOUND:
        body = {"id":1, "type_id": item_type_fixture.id-1, "is_available": True}
    post_response = client.post(url, json=body)
    assert post_response.status_code == response_status
