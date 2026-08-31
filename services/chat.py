"""AI 对话核心 — OpenAI Agents SDK 引擎"""

import os
import logging
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
    clear_agent_session_memory,
    suggest_categories,
    get_category_tools,
    generate_random_chat_id,
    init_chat_session,
    MAX_HISTORY_MESSAGES,
)
from services.memory import schedule_memory_extraction

logger = logging.getLogger(__name__)

# 失败时的友好兜底文案：不把异常裸抛给前端，也不让记忆库留下半截工具序列
FALLBACK_MESSAGE = "抱歉，我这边出了点问题，暂时没能完成这个请求。你可以换个说法再试一次～"


def _legalize_history(items: List[dict]) -> List[dict]:
    """清洗历史窗口，避免悬空工具序列把模型请求打挂。

    借鉴 nanobot 的 find_legal_message_start 思路：SDK 按条数截断历史时，
    可能把窗口切在"工具调用"和"工具返回"中间，导致发给模型的消息里出现
    找不到来源的工具返回（或没有返回的工具调用），模型 API 会直接 400。
    这里在每次读取历史后做两个动作：
      1. 丢掉头部悬空的工具返回（前面没有对应的工具调用）；
      2. 丢掉尾部没有返回的工具调用（上一次运行中途崩溃留下的）。
    """
    if not items:
        return items

    # 1) 头部：丢弃找不到对应工具调用的工具返回
    declared: set = set()
    start = 0
    for i, item in enumerate(items):
        item_type = item.get("type")
        if item_type == "function_call":
            call_id = item.get("call_id")
            if call_id:
                declared.add(call_id)
        elif item_type == "function_call_output":
            call_id = item.get("call_id")
            if call_id and call_id not in declared:
                start = i + 1
                declared.clear()
    items = items[start:]

    # 2) 尾部：丢弃上次运行中途崩溃留下的、没有返回的工具调用
    answered = {
        i.get("call_id")
        for i in items
        if i.get("type") == "function_call_output" and i.get("call_id")
    }
    while items and items[-1].get("type") == "function_call" \
            and items[-1].get("call_id") not in answered:
        items.pop()

    return items


class SafeSQLiteSession(AdvancedSQLiteSession):
    """每次读取历史时自动清洗悬空工具序列，从源头避免模型 400。"""

    async def get_items(self, limit: Optional[int] = None, branch_id: Optional[str] = None):
        items = await super().get_items(limit=limit, branch_id=branch_id) # 调用父类方法获取原始数据
        cleaned = _legalize_history(items)
        if len(cleaned) != len(items):
            logger.warning(
                "agent history sanitized: %d -> %d items (session=%s)",
                len(items), len(cleaned), self.session_id,
            )
        return cleaned


async def chat(user_name: str, session_id: Optional[str], task: Optional[str],
               content: str, tools: List[str] = None):
    # 检查会话是否存在
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

    agent_session = SafeSQLiteSession(
        session_id=session_id,
        db_path="./assert/conversations.db",
        create_tables=True,
        session_settings=SessionSettings(limit=MAX_HISTORY_MESSAGES),
    )

    try:
        if not tools or len(tools) == 0:
            agent = Agent(
                name="Assistant",
                instructions=instructions,
                model=OpenAIChatCompletionsModel(
                    model=os.environ["OPENAI_MODEL"],
                    openai_client=external_client,
                ),
                model_settings=ModelSettings(parallel_tool_calls=False), # 控制是否允许多个工具调用并行执行
            )
            result = Runner.run_streamed(agent, input=content, session=agent_session)
            assistant_message = ""
            async for event in result.stream_events():
                if event.type == "raw_response_event":
                    if isinstance(event.data, ResponseTextDeltaEvent):
                        if event.data.delta:
                            yield event.data.delta
                            assistant_message += event.data.delta
            try:
                append_message2db(session_id, "assistant", assistant_message)
            except Exception:
                logger.exception("failed to persist assistant message")
            schedule_memory_extraction(user_name)
        else:
            async with mcp_server:
                # 工具调用上限：单次问答最多允许的工具调用次数（可用环境变量调整）
                MAX_TOOL_CALLS = int(os.environ.get("MAX_TOOL_CALLS", "5"))
                tool_call_count = 0

                agent = Agent(
                    name="Assistant",
                    instructions=instructions,
                    mcp_servers=[mcp_server],
                    model=OpenAIChatCompletionsModel(
                        model=os.environ["OPENAI_MODEL"],
                        openai_client=external_client,
                    ),
                    # 工具执行完后必须让模型再生成最终回答；不要 stop_on_first_tool，
                    # 否则这一轮只有工具调用没有答案，要等下一轮才显示
                    tool_use_behavior="run_llm_again",
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
                            if tool_call_count > MAX_TOOL_CALLS:
                                yield "\n[系统提示：工具调用次数已达上限，停止继续调用]\n"
                                assistant_message += "\n[系统提示：工具调用次数已达上限，停止继续调用]\n"
                                break
                            yield "\n```json\n" + event.data.item.name + ":" \
                                  + event.data.item.arguments + "\n" + "```\n\n"
                            assistant_message += "\n```json\n" + event.data.item.name + ":" \
                                                + event.data.item.arguments + "\n" + "```\n\n"

                    if event.type == "raw_response_event" and hasattr(event, 'data') \
                            and isinstance(event.data, ResponseTextDeltaEvent):
                        # 文本始终流式输出；工具执行完后模型会继续生成最终回答
                        yield event.data.delta
                        assistant_message += event.data.delta

                try:
                    append_message2db(session_id, "assistant", assistant_message)
                except Exception:
                    logger.exception("failed to persist assistant message")
                schedule_memory_extraction(user_name)
    except Exception:
        logger.exception("chat run failed for session %s", session_id)
        # 失败兜底：给用户一段友好文案，而不是静默/报错
        yield FALLBACK_MESSAGE
        try:
            append_message2db(session_id, "assistant", FALLBACK_MESSAGE)
        except Exception:
            logger.exception("failed to persist fallback message")
        # 清掉该会话记忆库里的残留，避免脏数据影响下一轮
        clear_agent_session_memory(session_id)
