"""LangChain 引擎 — AI 对话核心

与 services/chat.py（OpenAI Agents SDK）保持相同接口，可无缝切换。
"""

import json
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
)
from services.mcp_adapter import MCPClientManager


async def chat(
    user_name: str,
    session_id: Optional[str],
    task: Optional[str],
    content: str,
    tools: List[str] = None,
) -> AsyncGenerator[str, None]:
    """LangChain 版对话核心（接口与 agents 版本一致）"""

    # === 1. 会话初始化 ===
    if session_id:
        from models.orm import SessionLocal, ChatSessionTable as CST
        with SessionLocal() as session:
            record = session.query(CST).filter(CST.session_id == session_id).first()
            if not record:
                init_chat_session(user_name, content, session_id, task)

    append_message2db(session_id, "user", content)
    instructions = get_init_message(task)

    # === 2. 工具选择 ===
    if not tools:
        suggested_cats = suggest_categories(task)
        tools = []
        for cat in suggested_cats:
            tools.extend(get_category_tools(cat))
        tools = list(set(tools))

    need_viz_tools = {
        "get_month_line", "get_week_line", "get_day_line", "get_stock_minute_data",
    }
    has_viz = bool(set(need_viz_tools) & set(tools))
    tool_use_behavior = "stop_on_first_tool" if has_viz else "run_llm_again"

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
        await mcp_manager.connect()
        lc_tools = []
        if tools:
            lc_tools = await mcp_manager.get_langchain_tools(allowed_names=tools)

        if not tools or not lc_tools:
            # === 无工具：直接流式输出 ===
            messages = [
                SystemMessage(content=instructions),
                HumanMessage(content=content),
            ]
            assistant_message = ""
            async for chunk in llm.astream(messages):
                text = chunk.content if hasattr(chunk, "content") and chunk.content else ""
                if text:
                    yield text
                    assistant_message += text
            append_message2db(session_id, "assistant", assistant_message)
            return

        # === 5. 有工具：LangGraph ReAct Agent ===
        agent = create_react_agent(
            model=llm,
            tools=lc_tools,
            prompt=SystemMessage(content=instructions),
            version="v2",
        )

        # 手动维护工具调用上下文，用于 stop_on_first_tool
        tool_invoked = False
        tool_call_count = 0
        MAX_TOOL_CALLS = 10
        assistant_message = ""

        # 使用 astream_events 获取细粒度事件
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=content)]},
            version="v2",
        ):
            kind = event.get("event", "")

            # 工具调用事件 — 在任何模式下都记录
            if kind == "on_tool_start":
                tool_invoked = True
                tool_call_count += 1
                tool_input = event.get("data", {}).get("input", {})
                tool_name = event.get("name", "unknown")
                args_json = json.dumps(tool_input, ensure_ascii=False) if isinstance(tool_input, dict) else str(tool_input)
                yield f"\n```json\n{tool_name}:{args_json}\n```\n\n"
                assistant_message += f"\n```json\n{tool_name}:{args_json}\n```\n\n"

            # 工具调用结果事件 — stop_on_first_tool 在此截停
            if kind == "on_tool_end" and tool_use_behavior == "stop_on_first_tool":
                break

            # 超限截停
            if tool_call_count >= MAX_TOOL_CALLS and kind == "on_tool_start":
                msg = "\n[系统提示：工具调用次数已达上限，停止继续调用]\n"
                yield msg
                assistant_message += msg
                break

            # LLM 文本流 — run_llm_again 模式下才输出
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", {})
                text = chunk.content if hasattr(chunk, "content") and chunk.content else ""
                if tool_use_behavior != "stop_on_first_tool":
                    yield text
                assistant_message += text

        append_message2db(session_id, "assistant", assistant_message)

    finally:
        await mcp_manager.disconnect()
