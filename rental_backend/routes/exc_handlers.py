import starlette.requests
from starlette.responses import JSONResponse

from rental_backend.exceptions import (
    AlreadyExists,
    DateRangeError,
    ForbiddenAction,
    InactiveSession,
    NoneAvailable,
    ObjectNotFound,
    RateLimiterError,
    SessionExists,
    ValueError,
)
from rental_backend.schemas.base import StatusResponseModel

from .base import app


@app.exception_handler(ObjectNotFound)
async def not_found_handler(req: starlette.requests.Request, exc: ObjectNotFound):
    return JSONResponse(
        content=StatusResponseModel(status="Error", message=exc.eng, ru=exc.ru).model_dump(), status_code=404
    )


@app.exception_handler(AlreadyExists)
async def already_exists_handler(req: starlette.requests.Request, exc: AlreadyExists):
    return JSONResponse(
        content=StatusResponseModel(status="Error", message=exc.eng, ru=exc.ru).model_dump(), status_code=409
    )


@app.exception_handler(DateRangeError)
async def date_range_error_handler(req: starlette.requests.Request, exc: DateRangeError):
    return JSONResponse(
        content=StatusResponseModel(status="Error", message=exc.eng, ru=exc.ru).model_dump(), status_code=400
    )


@app.exception_handler(NoneAvailable)
async def none_available_error_handler(req: starlette.requests.Request, exc: NoneAvailable):
    return JSONResponse(
        content=StatusResponseModel(status="Error", message=exc.eng, ru=exc.ru).model_dump(), status_code=404
    )


@app.exception_handler(ForbiddenAction)
async def forbidden_action_error_handler(req: starlette.requests.Request, exc: ForbiddenAction):
    return JSONResponse(
        content=StatusResponseModel(status="Error", message=exc.eng, ru=exc.ru).model_dump(), status_code=403
    )


@app.exception_handler(InactiveSession)
async def inactive_session_error_handler(req: starlette.requests.Request, exc: InactiveSession):
    return JSONResponse(
        content=StatusResponseModel(status="Error", message=exc.eng, ru=exc.ru).model_dump(), status_code=409
    )


@app.exception_handler(SessionExists)
async def session_exists_error_handler(req: starlette.requests.Request, exc: SessionExists):
    return JSONResponse(
        content=StatusResponseModel(status="Error", message=exc.eng, ru=exc.ru).model_dump(), status_code=409
    )


@app.exception_handler(ValueError)
async def value_error_handler(req: starlette.requests.Request, exc: ValueError):
    return JSONResponse(
        content=StatusResponseModel(status="Error", message=exc.eng, ru=exc.ru).model_dump(), status_code=422
    )


@app.exception_handler(RateLimiterError)
async def rate_limiter_handler(req: starlette.requests.Request, exc: RateLimiterError):
    return JSONResponse(
        content=StatusResponseModel(status="Error", message=exc.eng, ru=exc.ru).model_dump(), status_code=429
    )
