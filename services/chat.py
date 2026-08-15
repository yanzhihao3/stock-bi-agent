"""AI 对话核心 — OpenAI Agents SDK 引擎"""

import os
import traceback
from typing import List, Optional

from agents import Agent, Runner, OpenAIChatCompletionsModel, ModelSettings
from agents.extensions.memory import AdvancedSQLiteSession
from agents.memory import SessionSettings
from agents.mcp import MCPServerSse, ToolFilterStatic
from openai import AsyncOpenAI
from openai.types.responses import ResponseTextDeltaEvent, ResponseOutputItemDoneEvent, ResponseFunctionToolCall

from services.chat_common import (
    get_init_message,
    append_message2db,
    suggest_categories,
    get_category_tools,
    generate_random_chat_id,
    init_chat_session,
    MAX_HISTORY_MESSAGES,
)


async def chat(user_name: str, session_id: Optional[str], task: Optional[str],
               content: str, tools: List[str] = None):
    # 检查会话是否存在
    if session_id:
        from models.orm import SessionLocal, ChatSessionTable as CST
        with SessionLocal() as session:
            record = session.query(CST).filter(CST.session_id == session_id).first()
            if not record:
                init_chat_session(user_name, content, session_id, task)

    append_message2db(session_id, "user", content)
    instructions = get_init_message(task)

    external_client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )

    # 工具选择
    if not tools or len(tools) == 0:
        suggested_cats = suggest_categories(task)
        tools = []
        for cat in suggested_cats:
            tools.extend(get_category_tools(cat))
        tools = list(set(tools))

    if not tools or len(tools) == 0:
        tool_mcp_tools_filter = None
    else:
        tool_mcp_tools_filter = ToolFilterStatic(allowed_tool_names=tools)

    mcp_server = MCPServerSse(
        name="SSE Python Server",
        params={"url": "http://localhost:8900/sse"},
        cache_tools_list=False,
        tool_filter=tool_mcp_tools_filter,
        client_session_timeout_seconds=20,
    )

    agent_session = AdvancedSQLiteSession(
        session_id=session_id,
        db_path="./assert/conversations.db",
        create_tables=True,
        session_settings=SessionSettings(limit=MAX_HISTORY_MESSAGES),
    )

    if not tools or len(tools) == 0:
        agent = Agent(
            name="Assistant",
            instructions=instructions,
            model=OpenAIChatCompletionsModel(
                model=os.environ["OPENAI_MODEL"],
                openai_client=external_client,
            ),
            model_settings=ModelSettings(parallel_tool_calls=False),
        )
        result = Runner.run_streamed(agent, input=content, session=agent_session)
        assistant_message = ""
        async for event in result.stream_events():
            if event.type == "raw_response_event":
                if isinstance(event.data, ResponseTextDeltaEvent):
                    if event.data.delta:
                        yield event.data.delta
                        assistant_message += event.data.delta
        append_message2db(session_id, "assistant", assistant_message)
    else:
        async with mcp_server:
            need_viz_tools = [
                "stock_get_month_line", "stock_get_week_line", "stock_get_day_line",
                "stock_get_minute_data",
            ]
            if set(need_viz_tools) & set(tools):
                tool_use_behavior = "stop_on_first_tool"
            else:
                tool_use_behavior = "run_llm_again"

            MAX_TOOL_CALLS = 10
            tool_call_count = 0

            agent = Agent(
                name="Assistant",
                instructions=instructions,
                mcp_servers=[mcp_server],
                model=OpenAIChatCompletionsModel(
                    model=os.environ["OPENAI_MODEL"],
                    openai_client=external_client,
                ),
                tool_use_behavior=tool_use_behavior,
                model_settings=ModelSettings(parallel_tool_calls=False), # 控制是否允许多个工具调用并行执行
            )

            result = Runner.run_streamed(agent, input=content, session=agent_session)
            assistant_message = ""
            current_tool_name = ""
            async for event in result.stream_events():
                if event.type == "raw_response_event" and hasattr(event, 'data') \
                        and isinstance(event.data, ResponseOutputItemDoneEvent):
                    if isinstance(event.data.item, ResponseFunctionToolCall):
                        current_tool_name = event.data.item.name
                        tool_call_count += 1
                        if tool_call_count >= MAX_TOOL_CALLS:
                            yield "\n[系统提示：工具调用次数已达上限，停止继续调用]\n"
                            assistant_message += "\n[系统提示：工具调用次数已达上限，停止继续调用]\n"
                            break
                        yield "\n```json\n" + event.data.item.name + ":" \
                              + event.data.item.arguments + "\n" + "```\n\n"
                        assistant_message += "\n```json\n" + event.data.item.name + ":" \
                                            + event.data.item.arguments + "\n" + "```\n\n"

                if event.type == "raw_response_event" and hasattr(event, 'data') \
                        and isinstance(event.data, ResponseTextDeltaEvent):
                    if tool_use_behavior != "stop_on_first_tool":
                        yield event.data.delta
                    assistant_message += event.data.delta

            append_message2db(session_id, "assistant", assistant_message)
