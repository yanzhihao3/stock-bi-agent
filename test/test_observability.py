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
    NOISY_LOGGERS,
    RequestIdFilter,
    RequestIdMiddleware,
    new_request_id,
    request_id,
    scrub_secrets,
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

    def test_url_leaking_loggers_are_quieted(self):
        """回归保护：这两个库必须留在降噪名单里。

        urllib3 在 DEBUG 级别会打完整请求 URL（query 里带 API key），
        实测把 whyta 的 key 明文写进了 logs/app-mcp.log；
        sse_starlette 会把整个工具列表 JSON 和每个 chunk 都记进 DEBUG。
        谁把这两个从名单里删掉，这个测试就红。
        """
        for name in ("urllib3", "sse_starlette"):
            assert name in NOISY_LOGGERS, f"{name} 必须留在降噪名单里"


class TestScrubSecrets:
    def test_redacts_url_query_key(self):
        text = 'GET https://whyta.cn/api/tianqi?key=abcdef123456&city=shanghai HTTP/1.1'
        out = scrub_secrets(text)
        assert "abcdef123456" not in out
        assert "key=***" in out
        assert "city=shanghai" in out  # 只抹密钥，别把别的参数也吃了

    def test_redacts_bearer_token(self):
        out = scrub_secrets("Authorization: Bearer sk-abcdef1234567890")
        assert "sk-abcdef1234567890" not in out
        assert "Bearer ***" in out

    def test_redacts_common_key_names(self):
        out = scrub_secrets("api_key=abc123 token: xyz password = p@ss")
        assert "abc123" not in out and "xyz" not in out and "p@ss" not in out

    def test_leaves_clean_text_alone(self):
        text = "上海今天 26 度，晴。"
        assert scrub_secrets(text) == text

    def test_empty_input(self):
        assert scrub_secrets("") == ""

    def test_does_not_touch_python_kwarg_in_dict_repr(self):
        """字典/JSON 里的 "key": "value" 形态不该被误伤。"""
        text = '{"key": "关注股票", "content": "用户关注茅台"}'
        assert scrub_secrets(text) == text

    def test_over_redacts_rather_than_under_redacts(self):
        """已知取舍：把 `key=foo` 这种非密钥写法也抹掉。

        故意的 —— 脱敏要保证"宁可多抹"，漏一个真密钥的代价比日志难看大得多。
        这条测试把这个取舍写成显式约定，而不是让它看起来像个意外。
        """
        assert scrub_secrets("sorted(items, key=some_lambda)") == "sorted(items, key=***)"

    def test_scrubbing_formatter_covers_traceback(self):
        """关键：堆栈里的 URL 也要被抹掉。

        requests 的异常文本里带完整 URL（含 key），而 logger.exception 的堆栈是
        formatter 单独拼上去的 —— 只在 Filter 里改 record.msg 覆盖不到这一块。
        """
        from services.observability import SecretScrubbingFormatter

        formatter = SecretScrubbingFormatter("%(message)s")
        try:
            raise ValueError("400 Client Error for url: https://api.autostock.cn/v1/stock?token=deadbeef1234")
        except ValueError:
            import sys

            record = logging.LogRecord("t", logging.ERROR, __file__, 1, "调用失败", None, sys.exc_info())
        output = formatter.format(record)
        assert "deadbeef1234" not in output
        assert "token=***" in output


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
        """嵌套 set/reset 必须按后进先出解开，且与外层绑什么值无关。

        对应 services/chat.py 里"路由层已经绑了 session_id、chat() 里再绑一次"。
        两边实际绑的是同一个值，但正确性**不依赖**值相同：reset(token) 还原的是
        「创建这个 token 那一刻 ContextVar 原本的值」，所以只要 set/reset 成对、
        后进先出，嵌套多少层都对。

        这里刻意让内外绑**不同**的值 —— 用不同的值才能证明上面那句话，
        用相同的值会让"还原对了"和"本来就没变"看起来一样。
        """

        async def inner():
            token = request_id.set("INNER")  # 故意和外层不同
            try:
                yield request_id.get()
            finally:
                request_id.reset(token)

        async def outer():
            outer_token = request_id.set("OUTER")
            try:
                seen = [value async for value in inner()]
                seen.append(request_id.get())  # 内层解开后，应当回到 OUTER
                return seen
            finally:
                request_id.reset(outer_token)

        assert asyncio.run(outer()) == ["INNER", "OUTER"]
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
