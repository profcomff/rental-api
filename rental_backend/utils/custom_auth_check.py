from typing import Any

from auth_lib.fastapi import UnionAuth
from starlette.requests import Request


class UnionAuthChecker(UnionAuth):
    def __call__(
        self,
        request: Request,
    ) -> dict[str, Any] | None:
        result = super().__call__(request)
        token = request.headers.get("Authorization")
        user_data_info = self._get_userdata(token, result["id"])
        if user_data_info is not None and len(user_data_info["items"]) != 0:
            union_member_info = list(filter(lambda x: "is_union_member" in x, user_data_info["items"]))
            phone_number_info = list(filter(lambda x: "phone_number" in x, user_data_info["items"]))
        else:
            self._except_not_authorized()
        if (
            len(union_member_info) == 0
            or union_member_info[0]["is_union_member"] is False
            or phone_number_info[0]["phone_number"] == ""
        ):
            self._except_not_authorized()
        return result
