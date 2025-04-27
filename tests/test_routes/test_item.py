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
    body = {"id": 0, "type_id": 0, "is_available": False}
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
