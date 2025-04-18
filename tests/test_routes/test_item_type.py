from typing import Dict, Any

import pytest
from starlette import status
from fastapi.testclient import TestClient
from sqlalchemy import desc

from rental_backend.models.base import BaseDbModel
from rental_backend.models.db import ItemType
from rental_backend.routes.item_type import item_type


# Utils for tests
def model_to_dict(model: BaseDbModel) -> Dict[str, Any]:
    """Возвращает поля модели БД в виде словаря."""
    model_dict = dict()
    for col in model.__table__.columns:
        model_dict[col.name] = getattr(model, col.name)
    return model_dict


# New fixtures for itemtype tests
@pytest.fixture
def base_itemtype_url(client: TestClient) -> str:
    """Формирует корневой URL для Item."""
    return f'{client.base_url}{item_type.prefix}'


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


# Tests for updating itemtype
@pytest.mark.parametrize(
    'payload, right_status_code',
    [
        ({'name': 'New ItemType', 'image_url': 'path_to_image', 'description': 'newnew'}, status.HTTP_200_OK),
        ({'image_url': 'path_to_image', 'description': 'newnew'}, status.HTTP_422_UNPROCESSABLE_ENTITY),
        ({'name': 'New ItemType', 'description': 'newnew'}, status.HTTP_200_OK),
        ({'name': 'New ItemType', 'image_url': 'path_to_image'}, status.HTTP_200_OK),
        ({'name': 'New ItemType'}, status.HTTP_200_OK),
        ({'name': 'New ItemType', 'image_url': 'path_to_image', 'description': 'newnew', 'extra': 'oops!'}, status.HTTP_200_OK),
        ({'name': 1, 'image_url': 'path_to_image', 'description': 'newnew'}, status.HTTP_422_UNPROCESSABLE_ENTITY),
        ({'name': 'New ItemType', 'image_url': True, 'description': 'newnew'}, status.HTTP_422_UNPROCESSABLE_ENTITY),
        ({'name': 'New ItemType', 'image_url': 'path_to_image', 'description': ['biba', 'boba']}, status.HTTP_422_UNPROCESSABLE_ENTITY),
        ({}, status.HTTP_422_UNPROCESSABLE_ENTITY),
        ({'name': 'Test ItemType'}, status.HTTP_409_CONFLICT),
        ({'name': 'Test ItemType', 'image_url': 'path_to_image', 'description': 'newnew'}, status.HTTP_200_OK)
    ],
    ids=['valid_new_payload',
         'invalid_new_without_name',
         'valid_new_without_url',
         'valid_new_without_desc',   
         'valid_new_only_name',
         'valid_new_with_extra_field',
         'invalid_name',
         'invalid_image_url',
         'inavalid_desc',
         'empty_payload',
         'full_old_payload',
         'part_old_payload']
)
def test_payload_for_update_itemtype(dbsession, item_type_fixture, client, base_itemtype_url, payload, right_status_code):
    """Проверка реакции ручки PATCH /itemtype на разные входные данные."""
    response = client.patch(f"{base_itemtype_url}/{item_type_fixture.id}", json=payload)
    assert response.status_code == right_status_code


@pytest.mark.parametrize(
    'payload, is_updated',
    [
        ({'name': 'New ItemType', 'image_url': 'path_to_image', 'description': 'newnew'}, True),
        ({'image_url': 'path_to_image', 'description': 'newnew'}, False),
        ({'name': 'New ItemType', 'description': 'newnew'}, True),
        ({'name': 'New ItemType', 'image_url': 'path_to_image'}, True),
        ({'name': 'New ItemType'}, True),
        ({'name': 'New ItemType', 'image_url': 'path_to_image', 'description': 'newnew', 'extra': 'oops!'}, True),
        ({'name': 1, 'image_url': 'path_to_image', 'description': 'newnew'}, False),
        ({'name': 'New ItemType', 'image_url': True, 'description': 'newnew'}, False),
        ({'name': 'New ItemType', 'image_url': 'path_to_image', 'description': ['biba', 'boba']}, False),
        ({}, False),
        ({'name': 'Test ItemType'}, False),
        ({'name': 'Test ItemType', 'image_url': 'path_to_image', 'description': 'newnew'}, True)
    ],
    ids=['valid_new_payload',
         'invalid_new_without_name',
         'valid_new_without_url',
         'valid_new_without_desc',   
         'valid_new_only_name',
         'valid_new_with_extra_field',
         'invalid_name',
         'invalid_image_url',
         'inavalid_desc',
         'empty_payload',
         'full_old_payload',
         'part_old_payload']
)
def test_update_itemtype_model(dbsession, item_type_fixture, client, base_itemtype_url, payload, is_updated):
    """Проверка наличия изменений в БД после отработки ручки PATCH /itemtype"""
    old_model_fields = model_to_dict(item_type_fixture)
    response = client.patch(f"{base_itemtype_url}/{item_type_fixture.id}", json=payload)
    dbsession.refresh(item_type_fixture)
    new_model_fields = model_to_dict(item_type_fixture)
    is_really_changed = old_model_fields != new_model_fields
    assert is_really_changed == is_updated


def test_update_itemtype_not_found(client, dbsession, base_itemtype_url):
    """Пробует обновить несуществующий ItemType.
    
    .. caution::
        Несуществующий id осуществляется без учета id 'soft deleted' ItemType.
        Поэтому возможны ошибки при изменении поведения ItemType.query().
    """
    payload = {
        'name': 'New ItemType',
        'image_url': 'path_to_image',
        'description': 'newnew'
    }
    try:
        unexisting_id = ItemType.query(session=dbsession).order_by(desc('id'))[0].id + 1
    except IndexError:
        unexisting_id = 1
    response = client.patch(f"{base_itemtype_url}/{unexisting_id}", json=payload)
    assert response.status_code == status.HTTP_404_NOT_FOUND
