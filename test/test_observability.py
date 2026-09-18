"""services/observability.py 的测试

重点是把「第 0 步探针」验证过的结论固化成回归测试：
ContextVar 在 FastAPI 的流式链路里到底传不传得下去，直接决定 request id
这套方案成不成立。这几个用例挂了，说明日志的关联能力坏了。
"""

import asyncio
import logging

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from services.observability import (
    RequestIdFilter,
    RequestIdMiddleware,
    new_request_id,
    request_id,
    setup_logging,
)

NOISY = ("httpx", "httpcore", "mcp", "openai", "uvicorn.access")


class _Capture(logging.Handler):
    """把日志记录收进内存，顺带执行 RequestIdFilter。"""

    def __init__(self):
        super().__init__()
        self.rows: list = []
        self.addFilter(RequestIdFilter())

    def emit(self, record):
        self.rows.append((record.request_id, record.getMessage()))

    def ids(self):
        return {rid for rid, _ in self.rows}


def _logger_with_capture(name: str) -> tuple:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = _Capture()
    logger.handlers = [handler]
    return logger, handler


@pytest.fixture
def restore_logging():
    """setup_logging 会改全局 logging，测完还原，别影响别的测试。"""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_noisy = {n: logging.getLogger(n).level for n in NOISY}
    yield
    for handler in root.handlers:
        if handler not in saved_handlers:
            handler.close()  # Windows 上不关会导致 tmp 目录删不掉
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    for name, level in saved_noisy.items():
        logging.getLogger(name).setLevel(level)


# ---------------------------------------------------------------- 过滤器本身


class TestRequestIdFilter:
    def test_defaults_to_dash_when_nothing_bound(self):
        handler = _Capture()
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "hi", None, None)
        assert handler.filter(record) is True
        assert record.request_id == "-"

    def test_injects_bound_value(self):
        handler = _Capture()
        token = request_id.set("SESS-XYZ")
        try:
            record = logging.LogRecord("t", logging.INFO, __file__, 1, "hi", None, None)
            handler.filter(record)
            assert record.request_id == "SESS-XYZ"
        finally:
            request_id.reset(token)

    def test_new_request_id_is_short_and_unique(self):
        ids = {new_request_id() for _ in range(50)}
        assert len(ids) == 50
        assert all(len(i) == 8 for i in ids)


# ---------------------------------------------------------------- 落盘


class TestSetupLogging:
    def test_writes_file_with_request_id(self, tmp_path, monkeypatch, restore_logging):
        monkeypatch.setenv("LOG_DIR", str(tmp_path))
        log_file = setup_logging("unittest")

        token = request_id.set("SESS-FILE-1")
        try:
            logging.getLogger("some.module").warning("落盘测试")
        finally:
            request_id.reset(token)

        content = log_file.read_text(encoding="utf-8")
        assert "落盘测试" in content
        assert "[SESS-FILE-1]" in content
        assert "some.module" in content  # 格式里有模块名，便于定位来源

    def test_quiets_noisy_third_party_loggers(self, tmp_path, monkeypatch, restore_logging):
        monkeypatch.setenv("LOG_DIR", str(tmp_path))
        setup_logging("unittest")
        for name in NOISY:
            assert logging.getLogger(name).level == logging.WARNING


# ---------------------------------------------------------------- 传播链路


def _streaming_app(capture_logger: logging.Logger) -> FastAPI:
    """复刻 routers/chat.py 的真实结构：StreamingResponse → 生成器 → 引擎生成器。"""
    app = FastAPI()

    async def engine_stream(session_id: str):
        capture_logger.info("engine: 处理中")
        for i in range(2):
            await asyncio.sleep(0.01)  # 让出事件循环，并发串号才会暴露
            capture_logger.info("engine: 第 %d 块", i)
            yield f"c{i}"

    async def stream_generator(session_id: str):
        token = request_id.set(session_id)
        try:
            async for chunk in engine_stream(session_id):
                yield chunk
        finally:
            request_id.reset(token)

    @app.post("/chat/{session_id}")
    async def chat(session_id: str):
        return StreamingResponse(stream_generator(session_id), media_type="text/event-stream")

    return app


class TestPropagation:
    def test_streaming_chain_carries_session_id(self):
        """核心用例：生成器里 set 的 id 必须能被内层引擎的 logger 看到。"""
        _, capture = _logger_with_capture("t_engine")
        app = _streaming_app(logging.getLogger("t_engine"))
        with TestClient(app) as client:
            response = client.post("/chat/SESS-abc123")

        assert response.status_code == 200
        assert "c0" in response.text and "c1" in response.text  # 流式内容完整
        assert capture.ids() == {"SESS-abc123"}
        assert len(capture.rows) == 3

    def test_concurrent_requests_do_not_cross(self):
        """并发隔离：两个请求各自的日志只能带自己的 id。"""
        _, capture = _logger_with_capture("t_engine_conc")
        app = _streaming_app(logging.getLogger("t_engine_conc"))

        async def main():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                await asyncio.gather(
                    c.post("/chat/SESS-AAA"),
                    c.post("/chat/SESS-BBB"),
                )

        asyncio.run(main())

        per_id = {}
        for rid, _ in capture.rows:
            per_id.setdefault(rid, 0)
            per_id[rid] += 1
        assert set(per_id) == {"SESS-AAA", "SESS-BBB"}
        # 每个会话都应该恰好留下自己那 3 条，混了就会多出来
        assert per_id == {"SESS-AAA": 3, "SESS-BBB": 3}

    def test_background_task_inherits_request_id(self):
        """请求返回后才跑完的后台任务（对应 schedule_memory_extraction）也要带 id。"""
        capture_logger, capture = _logger_with_capture("t_bg")
        app = FastAPI()

        async def background():
            await asyncio.sleep(0.05)
            capture_logger.info("background: 记忆提取完成")

        @app.post("/{session_id}")
        async def endpoint(session_id: str):
            token = request_id.set(session_id)
            try:
                asyncio.create_task(background())  # 继承创建时的上下文
            finally:
                request_id.reset(token)
            return {"ok": True}

        async def main():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                await c.post("/SESS-BG-1")
                await asyncio.sleep(0.2)

        asyncio.run(main())
        assert capture.ids() == {"SESS-BG-1"}

    def test_nested_binding_unwinds_cleanly(self):
        """chat.py 会在路由层已绑的基础上再绑一次同样的值，这里验证解开顺序。

        两层都绑 SESS-N：内层先解开，外层必须仍拿到 SESS-N（不是回落到默认值）。
        绑的是同一个值，所以顺序看起来无所谓 —— 但这是"看起来对"和"确实对"的区别，
        改动这一块（比如以后内外两层绑不同的值）会立刻让它变红。
        """

        async def inner():
            token = request_id.set("SESS-N")
            try:
                yield request_id.get()
            finally:
                request_id.reset(token)

        async def outer():
            outer_token = request_id.set("SESS-N")
            try:
                seen = [value async for value in inner()]
                seen.append(request_id.get())  # 内层解开之后，外层的值还在
                return seen
            finally:
                request_id.reset(outer_token)

        assert asyncio.run(outer()) == ["SESS-N", "SESS-N"]
        assert request_id.get() == "-"  # asyncio.run 用的是上下文副本


# ---------------------------------------------------------------- 中间件


class TestRequestIdMiddleware:
    def test_non_streaming_endpoint_sees_incoming_header(self):
        capture_logger, capture = _logger_with_capture("t_mw")
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.post("/plain")
        async def plain(request: Request):
            capture_logger.info("plain: 处理中")
            return {"id_in_scope": request.headers.get("x-request-id")}

        with TestClient(app) as client:
            client.post("/plain", headers={"x-request-id": "INCOMING-42"})

        assert capture.ids() == {"INCOMING-42"}

    def test_generates_id_when_header_absent(self):
        capture_logger, capture = _logger_with_capture("t_mw2")
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.post("/plain")
        async def plain():
            capture_logger.info("plain")
            return {"ok": True}

        with TestClient(app) as client:
            client.post("/plain")

        ids = capture.ids()
        assert len(ids) == 1
        assert "-" not in ids

    def test_resets_after_request(self):
        """请求结束后不能把 id 留在上下文里，否则下一个请求会继承上一个的。"""
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.post("/plain")
        async def plain():
            return {"ok": True}

        with TestClient(app) as client:
            client.post("/plain", headers={"x-request-id": "OUTER-1"})
            assert request_id.get() == "-"
