import pytest
from fastapi.testclient import TestClient
from starlette import status

from rental_backend.__main__ import app
from rental_backend.models.db import Item, ItemType
from rental_backend.schemas.base import StatusResponseModel
from rental_backend.schemas.models import ItemGet, ItemPost


client = TestClient(app)
url = '/item'
