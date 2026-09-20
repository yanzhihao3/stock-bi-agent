"""用户管理路由（JWT 认证版）

- 公开接口：登录、注册
- 登录态接口：查看/修改自己的信息、改密码、删除自己的账户
- 管理员接口：修改任意用户角色/状态、删除任意用户、查看用户列表

业务错误统一抛出 BusinessError，由全局异常处理器转成对应 HTTP 状态码。
"""

from typing import Optional

from fastapi import APIRouter, Depends

import services.user as user_service
from models.orm import USER_NAME_MAX
from models.data_models import (
    BasicResponse,
    RequestForUserChangeInfo,
    RequestForUserDelete,
    RequestForUserLogin,
    RequestForUserRegister,
    RequestForUserResetPassword,
)
from models.orm import UserTable
from services.auth import create_access_token, get_current_user, require_admin
from services.errors import BusinessError

router = APIRouter(prefix="/v1/users", tags=["users"])


def _ok(data=None, message: str = "ok") -> BasicResponse:
    return BasicResponse(code=200, message=message, data=data)


def _auth_data(user) -> dict:
    """登录/注册成功后返回的鉴权信息"""
    return {
        "token": create_access_token(user.user_name, user.user_role),
        "user_name": user.user_name,
        "user_role": user.user_role,
    }


@router.post("/login")
def user_login(req: RequestForUserLogin) -> BasicResponse:
    user = user_service.authenticate(req.user_name, req.password)
    if user is None:
        raise BusinessError(401, "用户名或密码错误")
    if not user.status:
        raise BusinessError(403, "账号已被禁用")
    return _ok(_auth_data(user), "登录成功")


@router.post("/register")
def user_register(req: RequestForUserRegister) -> BasicResponse:
    # 长度必须在入口拦住：MySQL 会强制 VARCHAR 的长度（SQLite 不强制），
    # 超长会抛 DataError 1406 变成 500。**这里不能截断** —— 截断会让两个不同的
    # 用户名变成同一个，注册冲突、登录串号，比报错严重得多。
    if len(req.user_name) > USER_NAME_MAX:
        raise BusinessError(400, f"用户名最长 {USER_NAME_MAX} 个字符")
    user = user_service.user_register(req.user_name, req.password)
    if user is None:
        raise BusinessError(400, "用户名已存在")
    return _ok(_auth_data(user), "用户注册成功")


@router.post("/reset-password")
def user_reset_password(
    req: RequestForUserResetPassword,
    user: UserTable = Depends(get_current_user),
) -> BasicResponse:
    """修改当前登录用户的密码，需要验证原密码"""
    if not user_service.check_password(user.user_name, req.password):
        raise BusinessError(400, "原密码错误")
    user_service.user_reset_password(user.user_name, req.new_password)
    return _ok(message="密码重置成功")


@router.post("/info")
def user_info(user: UserTable = Depends(get_current_user)) -> BasicResponse:
    """获取当前登录用户的信息（身份从 token 解析，无需传用户名）"""
    return _ok(user_service.get_user_info(user.user_name))


@router.post("/reset-info")
def user_reset_info(
    req: RequestForUserChangeInfo,
    admin: UserTable = Depends(require_admin),
) -> BasicResponse:
    """管理员修改任意用户的角色/状态"""
    if not user_service.check_user_exists(req.user_name):
        raise BusinessError(400, "用户不存在")
    if req.user_role is not None:
        user_service.alter_user_role(req.user_name, req.user_role)
    if req.status is not None:
        user_service.alter_user_status(req.user_name, req.status)
    return _ok(message="用户信息修改成功")


@router.post("/delete")
def user_delete(
    req: Optional[RequestForUserDelete] = None,
    user: UserTable = Depends(get_current_user),
) -> BasicResponse:
    """删除用户：不传 user_name 时删除自己；管理员可删除任意用户"""
    target = (req.user_name if req else None) or user.user_name
    if target != user.user_name and user.user_role != "管理员":
        raise BusinessError(403, "需要管理员权限")
    if not user_service.user_delete(target):
        raise BusinessError(400, "用户不存在")
    return _ok(message="用户删除成功")


@router.post("/list")
def user_list(admin: UserTable = Depends(require_admin)) -> BasicResponse:
    """管理员查看所有用户列表"""
    return _ok(user_service.list_users())
