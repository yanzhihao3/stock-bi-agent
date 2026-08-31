"""统一业务错误与全局异常处理

- BusinessError：路由层主动抛出的业务错误，携带 HTTP 状态码与给用户看的消息
- register_error_handlers(app)：注册到 FastAPI 应用
  - BusinessError → 对应 HTTP 状态码 + 统一响应体
  - 未捕获异常 → 500 + 通用错误（完整堆栈只进日志，不泄露给客户端）
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from models.data_models import BasicResponse

logger = logging.getLogger(__name__)


class BusinessError(Exception):
    """业务错误：HTTP 状态码 + 用户可见的错误消息"""

    def __init__(self, status_code: int = 400, message: str = "请求失败"):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def _error_response(status_code: int, message: str) -> JSONResponse:
    body = BasicResponse(code=status_code, message=message, data=[]).model_dump()
    return JSONResponse(status_code=status_code, content=body)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessError)
    async def _business_error_handler(request: Request, exc: BusinessError):
        return _error_response(exc.status_code, exc.message)

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("未捕获异常: %s %s", request.method, request.url.path)
        return _error_response(500, "服务器内部错误")
