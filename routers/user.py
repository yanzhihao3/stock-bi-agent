import traceback

from fastapi import FastAPI, APIRouter  # type: ignore

import services.user as user_service
from models.data_models import RequestForUserLogin, BasicResponse, RequestForUserRegister, RequestForUserResetPassword, \
    RequestForUserChangeInfo

router = APIRouter(prefix="/v1/users", tags=["users"])


# /v1/users/login
@router.post("/login")
def user_login(req: RequestForUserLogin) -> BasicResponse:
    try:
        if user_service.user_login(req.user_name, req.password):
            return BasicResponse(code=200, message="用户登陆成功", data=[])
        else:
            return BasicResponse(code=400, message="用户名或密码错误", data=[])
    except Exception as e:
        return BasicResponse(code=404, message=traceback.format_exc(), data=[])

# /v1/users/register
@router.post("/register")
def user_register(req: RequestForUserRegister) -> BasicResponse:
    try:
        if user_service.user_register(req.user_name, req.password, req.user_role):
            return BasicResponse(code=200, message="用户注册成功", data=[])
        else:
            return BasicResponse(code=400, message="用户名已存在", data=[])
    except Exception as e:
        return BasicResponse(code=404, message=traceback.format_exc(), data=[])


@router.post("/reset-password")
def user_reset_password(req: RequestForUserResetPassword) -> BasicResponse:
    try:
        if not user_service.user_login(req.user_name, req.password):
            return BasicResponse(code=400, message="用户名或密码错误", data=[])
        else:
            if user_service.user_reset_password(req.user_name, req.new_password):
                return BasicResponse(code=200, message="密码重置成功", data=[])
            else:
                return BasicResponse(code=200, message="密码重置失败", data=[])
    except Exception as e:
        return BasicResponse(code=404, message=traceback.format_exc(), data=[])


@router.post("/info")
def user_info(user_name: str) -> BasicResponse:
    try:
        if not user_service.check_user_exists(user_name):
            return BasicResponse(code=400, message="用户不存在", data=[])
        else:
            return BasicResponse(code=200, message="获取用户信息成功",
                                 data=user_service.get_user_info(user_name=user_name))
    except Exception as e:
        return BasicResponse(code=404, message=traceback.format_exc(), data=[])


@router.post("/reset-info")
def user_reset_info(req: RequestForUserChangeInfo) -> BasicResponse:
    try:
        if not user_service.check_user_exists(req.user_name):
            return BasicResponse(code=400, message="用户不存在", data=[])
        else:
            if req.user_role:
                user_service.alter_user_role(req.user_name, req.user_role)

            if req.status:
                user_service.alter_user_status(req.user_name, req.status)

            return BasicResponse(code=200, message="用户信息修改成功", data=[])
    except Exception as e:
        return BasicResponse(code=404, message=traceback.format_exc(), data=[])


@router.post("/delete")
def user_delete(user_name: str) -> BasicResponse:
    try:
        if not user_service.check_user_exists(user_name):
            return BasicResponse(code=400, message="用户不存在", data=[])
        else:
            user_service.user_delete(user_name)
            return BasicResponse(code=200, message="用户删除成功", data=[])
    except Exception as e:
        return BasicResponse(code=404, message=traceback.format_exc(), data=[])


@router.post("/list")
def user_list() -> BasicResponse:
    try:
        return BasicResponse(code=200, message="ok", data=user_service.list_users())
    except Exception as e:
        return BasicResponse(code=404, message=traceback.format_exc(), data=[])
