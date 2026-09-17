#!/usr/bin/env python
"""并发安全检查：多个请求同时使用**共享的** MCP 连接，会不会互相干扰。

背景
    MCP 连接改成了进程级共享（见 services/mcp_adapter.get_mcp_manager）——
    好处是省掉每轮 SSE 握手，也消除了"跨任务清理 cancel scope"导致的崩溃。
    代价是：多个请求会共用同一个 MCP 会话。

    MCP 的 ClientSession 用请求 ID 匹配响应，理论上支持并发，
    但理论不等于实测，所以有了这个脚本。

为什么不用 UI 点两次
    Streamlit 的 rerun 是串行的，两个标签页也几乎不可能真正同时发出请求。
    真正能压到共享连接上的是「同一个事件循环里并发多个 chat() 调用」。

用法
    python eval/concurrency_check.py                     # 默认 3 路并发，langchain 引擎
    python eval/concurrency_check.py --engine agents --n 5

前提
    main_mcp.py 要在 8900 端口运行（和评测脚本一样）。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_runner_helpers():
    """复用评测脚本里的"评测用户"准备逻辑，避免两处各写一份。"""
    spec = importlib.util.spec_from_file_location(
        "run_eval_mod", Path(__file__).with_name("run_eval.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 用不同类别的问题，避免多个请求挤在同一个工具上
QUESTIONS = [
    "上海今天天气怎么样",
    "贵州茅台最近的走势怎么样",
    "今天有什么新闻",
    "100 美元能换多少人民币",
    "贵州茅台这家公司基本面怎么样",
    "今天大盘怎么样",
]


async def one(chat_fn, question: str, session_id: str) -> str:
    chunks = []
    async for chunk in chat_fn(
        user_name="eval_bot", session_id=session_id, task=None,
        content=question, tools=None,
    ):
        chunks.append(chunk)
    return "".join(chunks)


async def main_async(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv

    os.environ["TRACE_PATH"] = str((ROOT / "logs" / "concurrency-traces.jsonl").resolve())
    os.chdir(ROOT)
    # 必须先加载 .env 再导入 services.*：
    # chat_common / auth 现在是"缺密钥就报错"的必填项，导入时就会检查。
    load_dotenv(ROOT / ".env")

    from services.chat_common import generate_random_chat_id

    if args.engine == "agents":
        from services.chat import chat as chat_fn
    else:
        from services.langchain_chat import chat as chat_fn

    helpers = _load_runner_helpers()
    helpers.check_mcp()          # 先探一下 8900，免得报一堆连接错误让人以为并发有问题
    helpers.ensure_eval_user(helpers.EVAL_USER)

    questions = (QUESTIONS * 3)[: args.n]
    print(f"并发 {args.n} 路（引擎 {args.engine}），同时发起：")
    for q in questions:
        print(f"  - {q}")
    print()

    started = asyncio.get_running_loop().time()
    # gather 会让这些协程在**同一个事件循环里交错执行** —— 这正是要压的场景：
    # 它们会同时向同一个 MCP 会话发请求。
    results = await asyncio.gather(
        *(one(chat_fn, q, generate_random_chat_id()) for q in questions),
        return_exceptions=True,
    )
    elapsed = asyncio.get_running_loop().time() - started

    failed = 0
    for q, result in zip(questions, results):
        if isinstance(result, BaseException):
            failed += 1
            print(f"  x  {q[:18]:<20} 异常: {type(result).__name__}: {result}")
            continue
        body = (result or "").strip()
        if len(body) < 10:
            failed += 1
            print(f"  x  {q[:18]:<20} 空回答（{len(body)} 字）")
        else:
            print(f"  OK {q[:18]:<20} {len(body)} 字")

    print()
    print(f"总耗时 {elapsed:.1f}s（{args.n} 路并发）")

    # 收尾：在同一个循环里关掉共享连接。
    # 不关的话，解释器退出时它会被 GC 在别的任务里收尾，刷出 cancel scope 报错，
    # 看起来像是并发出了问题 —— 其实只是没清理干净。
    try:
        from services.mcp_adapter import get_mcp_manager
        await get_mcp_manager().disconnect()
    except Exception:
        pass

    if failed:
        print(f"[失败] {failed}/{args.n} 路出了问题 —— 共享连接可能有并发问题")
        return 1
    print("[通过] 全部正常，共享连接在并发下没出问题")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="MCP 共享连接的并发安全检查")
    p.add_argument("--engine", choices=["agents", "langchain"], default="langchain")
    p.add_argument("--n", type=int, default=3, help="并发路数（默认 3）")
    args = p.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
