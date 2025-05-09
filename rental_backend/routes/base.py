from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_sqlalchemy import DBSessionMiddleware
from logger_middleware import LoggerMiddleware

from rental_backend import __version__
from rental_backend.routes.event import event
from rental_backend.routes.item import item
from rental_backend.routes.item_type import item_type
from rental_backend.routes.rental_session import rental_session
from rental_backend.routes.strike import strike
from rental_backend.settings import get_settings


settings = get_settings()
app = FastAPI(
    title='Сервис цифрового проката',
    description='Краткое описание',
    version=__version__,
    # Отключаем нелокальную документацию
    root_path=settings.ROOT_PATH if __version__ != 'dev' else '',
    docs_url=None if __version__ != 'dev' else '/docs',
    redoc_url=None,
)


app.add_middleware(
    DBSessionMiddleware,
    db_url=str(settings.DB_DSN),
    engine_args={"pool_pre_ping": True, "isolation_level": "AUTOCOMMIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

if __version__ != 'dev':
    app.add_middleware(LoggerMiddleware, service_id=settings.SERVICE_ID)

app.include_router(event)
app.include_router(item)
app.include_router(rental_session)
app.include_router(item_type)
app.include_router(strike)
