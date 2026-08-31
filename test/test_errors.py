"""统一错误处理单元测试"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.errors import BusinessError, register_error_handlers

app = FastAPI()
register_error_handlers(app)


@app.get("/business")
def business():
    raise BusinessError(403, "无权访问")


@app.get("/crash")
def crash():
    raise RuntimeError("internal-secret-detail")


# raise_server_exceptions=False：断言客户端实际收到的响应；
# 默认 True 时 Starlette 会把已处理的服务端异常重新抛出给测试进程
client = TestClient(app, raise_server_exceptions=False)


class TestErrorHandlers:
    def test_business_error_has_proper_status_and_body(self):
        resp = client.get("/business")
        assert resp.status_code == 403
        body = resp.json()
        assert body["code"] == 403
        assert body["message"] == "无权访问"

    def test_unhandled_error_is_sanitized(self):
        resp = client.get("/crash")
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "服务器内部错误"
        assert "internal-secret-detail" not in resp.text
