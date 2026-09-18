"""统一日志配置 + request id 贯穿

单独一个模块的原因：日志配置要在进程启动时只做一次，而且后端（8000）和 MCP（8900）
两个进程都要用；request id 则要能被任意模块随时取到，所以放在最底层、不依赖业务代码。

设计背景（都是实测出来的，改之前先看一眼）：

1. 这个模块出现之前，项目**根本没有配置过日志** —— 11 个模块都有
   `logging.getLogger(__name__)`，但没有 basicConfig/dictConfig/handler，
   于是 `logger.warning/exception` 走 Python 的"最后兜底"处理器，只打 stderr、
   没有时间戳、不落盘；`logger.info/debug` 更是被直接丢弃。
   后果是一次真实故障：K 线接口静默返回空数组（HTTP 200 + data:[]），
   不报错、不记日志，一直没人发现。

2. request id 用 ContextVar 而不是全局变量：ContextVar 按 asyncio 任务隔离，
   两个人同时提问不会串号（已用探针验证：并发两个请求各 7 条日志，互不污染）。
   另外 `asyncio.create_task` 会**继承创建时的上下文**，所以
   services/memory.py 那种"请求返回后才跑完"的后台任务，日志照样带得上 id。
"""

from __future__ import annotations

import contextvars
import logging
import logging.config
import os
import uuid
from pathlib import Path

# 日志里那个可检索的关联键。
#
# 刻意只留一个字段，而不是 request_id + session_id 两个：
#   - 普通 HTTP 请求 → 中间件生成（或沿用它带进来的 X-Request-ID）
#   - 对话链路       → 由 routers/chat.py 覆盖成 session_id
# 一次聊天就是一个 session，拿 session_id 就能捞出全过程；再塞一个 request_id
# 进去，只会让人纠结该 grep 哪一个。
request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_LEVEL = "INFO"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# 这些库要么本身很吵，要么会把请求细节刷满日志，统一压到 WARNING。
#   asyncio —— 实测文件里会刷满 "Using proactor: IocpProactor" 这类 DEBUG；
#             压到 WARNING 后 "Task exception was never retrieved" 仍然保留
# 刻意**不**压 uvicorn.error —— 端口占用、启动失败这些堆栈都在它那儿。
NOISY_LOGGERS = ("httpx", "httpcore", "mcp", "openai", "asyncio", "uvicorn.access")


class RequestIdFilter(logging.Filter):
    """把当前任务的 request_id 塞进每条日志记录，供格式串取用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


def new_request_id() -> str:
    """短 id。日志里够区分就行，不需要 UUID 那么长。"""
    return uuid.uuid4().hex[:8]


def setup_logging(service: str) -> Path:
    """进程启动时调用一次，返回日志文件路径。

    service 用来区分日志文件名：后端和 MCP 是两个进程，写同一个文件
    在 Windows 上会互相抢锁。
    """
    log_dir = Path(os.environ.get("LOG_DIR", DEFAULT_LOG_DIR))
    level = os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"app-{service}.log"

    logging.config.dictConfig({
        "version": 1,
        # 必须是 False：uvicorn 启动时也会调 dictConfig 配自己的 logger，
        # 设成 True 会把它已经配好的 handler 摘掉，连启动日志都看不见
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": RequestIdFilter}},
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "filters": ["request_id"],
                "level": level,
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "filters": ["request_id"],
                # 文件永远收 DEBUG：排查时才需要细节，控制台不必被刷屏。
                # 用 LOG_LEVEL 的话，默认 INFO 就永远看不到 debug 行了。
                "level": "DEBUG",
                "filename": str(log_file),
                "maxBytes": LOG_MAX_BYTES,
                "backupCount": LOG_BACKUP_COUNT,
                "encoding": "utf-8",
            },
        },
        "root": {"level": "DEBUG", "handlers": ["console", "file"]},
    })

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "日志已配置 service=%s file=%s console_level=%s", service, log_file, level
    )
    return log_file


class RequestIdMiddleware:
    """给每个 HTTP 请求绑定一个 id 的纯 ASGI 中间件。

    刻意**不用** `@app.middleware("http")`：那会把整个应用包成 BaseHTTPMiddleware，
    它要额外起任务组、还要缓冲响应体，对流式接口（SSE）是多余的风险面。
    探针里两种方式都验证过能让 id 传下去，这里选更轻的那种。

    也刻意**不回写** `X-Request-ID` 响应头：对话请求会在流式生成器里把 id 覆盖成
    session_id，中间件拿不到那个值 —— 回写一个对不上的 id 只会误导排查。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or {}).get(b"x-request-id")
        rid = incoming.decode("latin-1") if incoming else new_request_id()
        token = request_id.set(rid)
        try:
            await self.app(scope, receive, send)
        finally:
            # 必须 reset：uvicorn 一个 worker 处理完请求后这个任务可能被复用，
            # 不还原的话 id 会残留到下一个请求上
            request_id.reset(token)
