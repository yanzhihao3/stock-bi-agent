"""自选股路由（JWT 认证版），用户身份从 token 解析"""

from fastapi import APIRouter, Depends

import services.stock as service_stock
from models.data_models import BasicResponse
from models.orm import UserTable
from services.auth import get_current_user
from services.errors import BusinessError

router = APIRouter(prefix="/v1/stock", tags=["stocks"])


def _ok(data=None, message: str = "ok") -> BasicResponse:
    return BasicResponse(code=200, message=message, data=data)


@router.post("/list_fav_stock")
def get_user_all_stock(user: UserTable = Depends(get_current_user)):
    return _ok(service_stock.get_user_all_stock(user.user_name))


@router.post("/del_fav_stock")
def delete_user_stock(stock_code: str, user: UserTable = Depends(get_current_user)):
    if not service_stock.delete_user_stock(user.user_name, stock_code):
        raise BusinessError(400, "用户不存在")
    return _ok(message="删除成功")


@router.post("/add_fav_stock")
def add_user_stock(stock_code: str, user: UserTable = Depends(get_current_user)):
    if not service_stock.add_user_stock(user.user_name, stock_code):
        raise BusinessError(400, "添加失败（可能已存在或用户不存在）")
    return _ok(message="添加成功")


@router.post("/clear_fav_stock")
def clear_user_stock(user: UserTable = Depends(get_current_user)):
    if not service_stock.clear_user_stock(user.user_name):
        raise BusinessError(400, "清空失败（用户不存在）")
    return _ok(message="清空成功")
