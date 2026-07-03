import os
import pytest

from agents.extensions.memory import AdvancedSQLiteSession
from openai import AsyncOpenAI

# 从系统环境变量读取配置
# 运行测试前请确保已设置 OPENAI_API_KEY 等环境变量


import asyncio
from openai.types.responses import ResponseTextDeltaEvent
from agents import Agent, Runner, OpenAIChatCompletionsModel
from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

async def test_agent_memory():
    external_client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )

    session = AdvancedSQLiteSession(
        session_id="test1",
        db_path="../assert/conversations.db",
        create_tables=True
    )
    # session：这是实现记忆功能的关键。它会将会话历史存储在 ./assert/conversations.db 这个 SQLite 数据库文件中，并且这个会话的 ID 是 test1。

    agent = Agent(
        name="Assistant",
        instructions="你好，你是小王",
        model=OpenAIChatCompletionsModel(
            model=os.environ["OPENAI_MODEL"],
            openai_client=external_client,
        ),
    )

    result = Runner.run_streamed(agent, input="你叫什么名字", session=session)
    async for event in result.stream_events():
        if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
            print(event.data.delta, end="", flush=True)

    result = Runner.run_streamed(agent, input="我之前的问题是什么？", session=session)
    async for event in result.stream_events():
        if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
            print(event.data.delta, end="", flush=True)
if __name__ == "__main__":
    asyncio.run(test_agent_memory())
