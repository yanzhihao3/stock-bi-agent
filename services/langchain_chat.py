"""LangChain 引擎 — AI 对话核心

与 services/chat.py（OpenAI Agents SDK）保持相同接口，可无缝切换。
"""

import json
import logging
import os
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
)
from services.memory import schedule_memory_extraction
from services.mcp_adapter import MCPClientManager

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
    )

    # === 4. 连接 MCP 并获取 LangChain 工具 ===
    mcp_manager = MCPClientManager("http://localhost:8900/sse")

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
                    msg = "\n[系统提示：工具调用次数已达上限，停止继续调用]\n"
                    yield msg
                    assistant_message += msg
                    break
                tool_call_count += 1
                tool_input = event.get("data", {}).get("input", {})
                tool_name = event.get("name", "unknown")
                args_json = json.dumps(tool_input, ensure_ascii=False) if isinstance(tool_input, dict) else str(tool_input)
                yield f"\n```json\n{tool_name}:{args_json}\n```\n\n"
                assistant_message += f"\n```json\n{tool_name}:{args_json}\n```\n\n"

            # LLM 文本流 — 始终流式输出；工具执行完后模型会继续生成最终回答
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", {})
                text = chunk.content if hasattr(chunk, "content") and chunk.content else ""
                yield text
                assistant_message += text

        try:
            append_message2db(session_id, "assistant", assistant_message)
        except Exception:
            logger.exception("failed to persist assistant message")
        schedule_memory_extraction(user_name)

    finally:
        await mcp_manager.disconnect() # 手动 disconnect()。
