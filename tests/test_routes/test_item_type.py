import pytest
from starlette import status

from rental_backend.models.db import ItemType


url = '/itemtype'


def test_get_item_type(client, items_with_types):
    _, item_types = items_with_types
    response = client.get(f'{url}/{item_types[0].id}')
    assert response.status_code == status.HTTP_200_OK
    random_id = 9999
    response = client.get(f'{url}/{random_id}')
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize(
    'type_id, response_status',
    [(0, status.HTTP_200_OK), (1, status.HTTP_200_OK)],
)
def test_get_item_types(client, items_with_types, type_id, response_status):
    _, item_types = items_with_types
    response = client.get(f'{url}/{item_types[type_id].id}')
    assert response.status_code == response_status
    if response_status == status.HTTP_200_OK:
        json_response = response.json()
        assert json_response["name"] == item_types[type_id].name
