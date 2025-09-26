from typing import Type


class RentalApiError(Exception):
    eng: str
    ru: str

    def __init__(self, eng: str, ru: str) -> None:
        self.eng = eng
        self.ru = ru
        super().__init__(eng)


class ObjectNotFound(RentalApiError):
    def __init__(self, obj: type, obj_id_or_name: int | str):
        super().__init__(
            f"Object {obj.__name__} {obj_id_or_name=} not found",
            f"Объект {obj.__name__}  с идентификатором {obj_id_or_name} не найден",
        )


class ValueError(RentalApiError):
    def __init__(self, value: str):
        super().__init__(f"Value {value} is not valid", f"Значение {value} недопустимо")


class AlreadyExists(RentalApiError):
    def __init__(self, obj: type, obj_id_or_name: int | str):
        super().__init__(
            f"Object {obj.__name__}, {obj_id_or_name=} already exists",
            f"Объект {obj.__name__} с идентификатором {obj_id_or_name=} уже существует",
        )


class ForbiddenAction(RentalApiError):
    def __init__(self, type: Type):
        super().__init__(f"Forbidden action with {type.__name__}", f"Запрещенное действие с объектом {type.__name__}")


class DateRangeError(RentalApiError):
    def __init__(self):
        super().__init__(
            "Both 'from_date' and 'to_date' must be provided together",
            "Оба параметра 'from_date' и 'to_date' должны быть переданы вместе",
        )


class NoneAvailable(RentalApiError):
    def __init__(self, obj: type, obj_id_or_name: int | str):
        super().__init__(
            f"The is no items of type {obj_id_or_name} available at the moment",
            f"В данный момент нет доступных предметов с идентификатором {obj_id_or_name}",
        )


class InactiveSession(RentalApiError):
    def __init__(self, obj: type, obj_id_or_name: int | str):
        super().__init__(
            f"Unable to end the session with id {obj_id_or_name} because it isn't active",
            f"Нельзя завершить сессию с id {obj_id_or_name}, потому то она не активна",
        )


class SessionExists(RentalApiError):
    def __init__(self, obj: type, obj_id_or_name: int | str):
        super().__init__(
            f"Session with an object of this type {obj_id_or_name} already exists",
            f"Сессия с объектом данного типа {obj_id_or_name} уже существует",
        )


class RateLimiterError(RentalApiError):
    def __init__(self, obj_id_or_name: int | str, minutes: int):
        super().__init__(
            f"Too many requests. Try again in {minutes} minutes",
            f"Слишком много запросов. Попробуйте снова через {minutes} минут",
        )
