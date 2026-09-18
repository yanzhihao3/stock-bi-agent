"""LangChain 引擎 — AI 对话核心

与 services/chat.py（OpenAI Agents SDK）保持相同接口，可无缝切换。
"""

import json
import logging
import os
import time
from typing import AsyncGenerator, List, Optional

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from services.chat_common import (
    get_init_message,
    append_message2db,
    suggest_categories,
    get_category_tools,
    init_chat_session,
    get_chat_sessions,
    MAX_HISTORY_MESSAGES,
    append_trace,
    log_tool_result,
    normalize_tool_args,
    summarize_tool_output,
    truncate_for_trace,
    body_chars,
    LIMIT_NOTICE,
    BUDGET_EXHAUSTED_PROMPT,
    EMPTY_FINAL_RESPONSE_MESSAGE,
)
from services.memory import schedule_memory_extraction
from services.mcp_adapter import get_mcp_manager
from services.observability import new_request_id, request_id

logger = logging.getLogger(__name__)


def _build_history_messages(session_id: Optional[str], user_name: str, content: str) -> list:
    """从数据库载入会话历史（不含 system），末尾为当前用户消息，受滑窗限制"""
    messages = []
    if session_id:
        history = get_chat_sessions(session_id, user_name) or []
        for m in sorted(history, key=lambda x: x["id"]):
            if m["role"] == "system":
                continue
            if m["role"] == "user":
                messages.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                messages.append(AIMessage(content=m["content"]))
    if len(messages) > MAX_HISTORY_MESSAGES:
        messages = messages[-MAX_HISTORY_MESSAGES:]
    while messages and not isinstance(messages[0], HumanMessage):
        messages.pop(0)
    if not any(isinstance(m, HumanMessage) for m in messages):
        messages.append(HumanMessage(content=content))
    return messages


async def chat(
    user_name: str,
    session_id: Optional[str],
    task: Optional[str],
    content: str,
    tools: List[str] = None,
) -> AsyncGenerator[str, None]: # AsyncGenerator[str, None]，表示这是个异步生成器函数（每次 yield 吐一个字）。
    """LangChain 版对话核心（接口与 agents 版本一致）"""

    # === 1. 会话初始化 ===
    # 运行轨迹：与 services/chat.py 保持同样的字段结构，便于评测脚本统一处理
    trace = {
        "engine": "langchain",
        "question": content,
        "task": task,
        "session_id": session_id,
        "tool_calls": [],
        # 工具返回的内容（截断后），与 chat.py 同名同结构
        "tool_results": [],
        # 本轮完整回答（含工具调用 JSON 块），离线核对时先用 answer_body() 剥掉
        "answer": "",
        "answer_chars": 0,
        "body_chars": 0,
        "truncated": False,
        "stop_reason": "completed",
        "elapsed_ms": None,
        "error": None,
    }
    trace_started = time.perf_counter()
    assistant_message = ""

    if session_id:
        from models.orm import SessionLocal, ChatSessionTable as CST
        with SessionLocal() as session:
            record = session.query(CST).filter(CST.session_id == session_id).first()
            if not record:
                init_chat_session(user_name, content, session_id, task)

    try:
        append_message2db(session_id, "user", content)
    except Exception:
        logger.exception("failed to persist user message")
    instructions = get_init_message(task, user_name)

    # === 2. 工具选择 ===
    if not tools:
        suggested_cats = suggest_categories(task)
        tools = []
        for cat in suggested_cats:
            tools.extend(get_category_tools(cat))
        tools = list(set(tools))

    # === 3. 初始化 LLM ===
    llm = ChatOpenAI(
        model=os.environ["OPENAI_MODEL"],
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
        temperature=0,
        streaming=True,
        # 打开流式下的 token 用量统计：默认关闭，开启后最后一个 chunk 会带 usage_metadata
        stream_usage=True,
    )

    # === 4. 连接 MCP 并获取 LangChain 工具 ===
    # 进程级共享连接，不再每轮新建/断开（原因见 get_mcp_manager 的说明）
    mcp_manager = get_mcp_manager()

    # 与 chat.py 同样再绑一次 session_id：评测脚本直接调用 chat()，不经过路由层。
    # 位置贴着 try —— 绑太早的话，中间抛异常时 finally 跑不到，id 会残留。
    request_token = request_id.set(session_id or new_request_id())

    try:
        await mcp_manager.connect()  # 手动连接 MCP
        lc_tools = []
        if tools:
            lc_tools = await mcp_manager.get_langchain_tools(allowed_names=tools) # 手动获取工具

        if not tools or not lc_tools:
            # === 无工具：直接流式输出 ===
            messages = [SystemMessage(content=instructions)]
            messages.extend(_build_history_messages(session_id, user_name, content))
            assistant_message = ""
            async for chunk in llm.astream(messages): # ← 直接调 LLM，没有 Agent
                text = chunk.content if hasattr(chunk, "content") and chunk.content else ""
                meta = getattr(chunk, "usage_metadata", None)
                if meta:
                    trace["usage"] = {
                        "input_tokens": meta.get("input_tokens"),
                        "output_tokens": meta.get("output_tokens"),
                        "total_tokens": meta.get("total_tokens"),
                    }
                if text:
                    yield text
                    assistant_message += text
            try:
                append_message2db(session_id, "assistant", assistant_message)
            except Exception:
                logger.exception("failed to persist assistant message")
            schedule_memory_extraction(user_name)
            return

        # === 5. 有工具：LangGraph ReAct Agent ===
        agent = create_react_agent(
            model=llm,  # ChatOpenAI
            tools=lc_tools, # 从 mcp_adapter 翻译来的工具
            prompt=SystemMessage(content=instructions),
            version="v2",
        )

        tool_call_count = 0
        # 工具调用上限：单次问答最多允许的工具调用次数（可用环境变量调整）
        MAX_TOOL_CALLS = int(os.environ.get("MAX_TOOL_CALLS", "5"))
        assistant_message = ""
        # 收集本轮的工具返回，超限时用来兜底总结
        tool_outputs: List[str] = []
        # run_id → 调用参数。on_tool_end 事件里不带参数，靠这个回查
        tool_args_by_run: dict = {}

        # 使用 astream_events 获取细粒度事件
        async for event in agent.astream_events(
            {"messages": _build_history_messages(session_id, user_name, content)},
            version="v2",
        ):
            kind = event.get("event", "")

            # 工具调用事件 — 在任何模式下都记录
            if kind == "on_tool_start":
                # 超限检查放在最先，避免"先宣告第 N+1 次调用再截停"的边界问题
                if tool_call_count >= MAX_TOOL_CALLS:
                    trace["truncated"] = True
                    msg = LIMIT_NOTICE
                    yield msg
                    assistant_message += msg
                    break
                tool_call_count += 1
                tool_input = event.get("data", {}).get("input", {})
                tool_name = event.get("name", "unknown")
                # 记下参数，on_tool_end 那个事件里没有参数
                tool_args_by_run[event.get("run_id")] = tool_input
                trace["tool_calls"].append({"name": tool_name, "args": normalize_tool_args(tool_input)})
                args_json = json.dumps(tool_input, ensure_ascii=False) if isinstance(tool_input, dict) else str(tool_input)
                yield f"\n```json\n{tool_name}:{args_json}\n```\n\n"
                assistant_message += f"\n```json\n{tool_name}:{args_json}\n```\n\n"

            # 工具执行结果 — 收集起来给兜底总结用
            if kind == "on_tool_end":
                out = event.get("data", {}).get("output")
                if out is not None:
                    text = getattr(out, "content", None) or str(out)
                    tool_outputs.append(str(text))
                    name = event.get("name", "unknown")
                    summary = summarize_tool_output(text)
                    log_tool_result(name, tool_args_by_run.get(event.get("run_id")), summary)
                    # 直接写进 trace（而不是局部变量）：trace 在函数开头就建好了，
                    # 中途抛异常时 finally 里也不会有"变量未定义"的风险
                    trace["tool_results"].append({
                        "name": name,
                        "output": truncate_for_trace(text),
                        "size": summary["size"],
                        "empty": summary["empty"],
                        "error": summary["error"],
                    })

            # LLM 文本流 — 始终流式输出；工具执行完后模型会继续生成最终回答
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", {})
                text = chunk.content if hasattr(chunk, "content") and chunk.content else ""
                meta = getattr(chunk, "usage_metadata", None)
                if meta:
                    trace["usage"] = {
                        "input_tokens": meta.get("input_tokens"),
                        "output_tokens": meta.get("output_tokens"),
                        "total_tokens": meta.get("total_tokens"),
                    }
                yield text
                assistant_message += text

        # 超限了 → 与 agents 引擎同样的兜底：禁止再调工具，基于已有数据作答。
        # 差别在于 langchain 的会话历史存在数据库里、不含本轮工具的原始返回，
        # 所以这里要把本轮收集到的工具输出显式拼进提示。
        if trace["truncated"]:
            trace["stop_reason"] = "max_tool_calls"
            hint = BUDGET_EXHAUSTED_PROMPT
            if tool_outputs:
                joined = "\n---\n".join(tool_outputs)[:8000]
                hint += "\n\n【本轮已获取的工具数据（超长已截断）】\n" + joined
            final_messages = [SystemMessage(content=instructions)]
            final_messages.extend(_build_history_messages(session_id, user_name, content))
            final_messages.append(HumanMessage(content=hint))
            async for chunk in llm.astream(final_messages):
                text = chunk.content if hasattr(chunk, "content") and chunk.content else ""
                if text:
                    yield text
                    assistant_message += text
            if body_chars(assistant_message) == 0:
                yield EMPTY_FINAL_RESPONSE_MESSAGE
                assistant_message += EMPTY_FINAL_RESPONSE_MESSAGE

        try:
            append_message2db(session_id, "assistant", assistant_message)
        except Exception:
            logger.exception("failed to persist assistant message")
        schedule_memory_extraction(user_name)

    finally:
        request_id.reset(request_token)
        # 注意：这里刻意**不再**调用 mcp_manager.disconnect()。
        # 原先每轮断开会造成两个后果：
        #   1. 下一个请求重新建一个 sse_client 上下文，旧上下文被 GC 时在别的任务里关闭，
        #      触发 "Attempted to exit cancel scope in a different task" 并把当前连接一起取消；
        #   2. 重复的握手和 list_tools 白白浪费。
        # 现在连接由 get_mcp_manager() 持有、随进程存活，单次对话结束只需要落盘轨迹。
        trace["answer"] = assistant_message
        trace["answer_chars"] = len(assistant_message)
        trace["body_chars"] = body_chars(assistant_message)
        trace["elapsed_ms"] = int((time.perf_counter() - trace_started) * 1000)
        append_trace(trace)
