import traceback

from agents import Agent, OpenAIChatCompletionsModel, Runner
from agents.extensions.memory import AdvancedSQLiteSession
from fastapi import FastAPI, APIRouter  # type: ignore
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
from typing import Union
import os  # Need to import os for environment variables

import services.chat as chat_services
from models.data_models import BasicResponse, RequestForChat, ResponseForChat
from agents import set_default_openai_api, set_tracing_disabled

set_default_openai_api("chat_completions")
set_tracing_disabled(True)



# 这是一个完整的聊天对话 API 路由模块，使用 FastAPI 构建，提供了聊天、会话管理、历史记录等 6 个接口。

router = APIRouter(prefix="/v1/chat", tags=["chat"])
# 作用：创建一个路由分组，所有接口都挂载在 /v1/chat 路径下  tags=["chat"]：在 API 文档中归类为 "chat" 组


@router.post("/")
# 核心聊天接口
async def chat(req: RequestForChat) -> StreamingResponse:
    try:
        # req: RequestForChat	接收前端传来的参数（用户名、消息内容等）
        # 异步函数

        # triage handoff 任务分发agent -》 master agent -》 任务分发
        # 帮我查询xx数据库中用户的总数是什么？ -》 db_agent 回答这个问题；
        # 帮我查询北京天气？ =》调用带 mcp 的 agent 回答这个问题；

        async def chat_stream_generator():
            # async for 遍历异步数据流
            async for chunk in chat_services.chat(
                    user_name=req.user_name,
                    task=req.task,
                    session_id=req.session_id,
                    content=req.content,
                    tools=req.tools
            ):
                # 每次迭代获取一个数据块并立即 yield 返回 # 逐字返回
                yield chunk   # 配合 下面的 StreamingResponse

        # Server-Sent Events (SSE) sse 对话流式输出，实时数据流
        return StreamingResponse(
            content=chat_stream_generator(),
            media_type="text/event-stream"   # SSE 格式 告诉前端"我要开始给你不间断地发消息了，你准备好逐字接收
        )
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/init")
#  初始化会话
async def init_chat() -> StreamingResponse:
    try:
        return BasicResponse(
            code=200, message="ok",
            data={
                "session_id": chat_services.generate_random_chat_id()
            }
        )
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/get")
def get_chat(session_id: str, user_name: str) -> BasicResponse:
    try:
        response = chat_services.get_chat_sessions(session_id, user_name)
        if response is None:
            return BasicResponse(code=403, message="无权查看该会话", data=[])
        return BasicResponse(
            code=200, message="ok",
            data=response
        )
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/delete")
def delete_chat(session_id: str, user_name: str) -> BasicResponse:
    try:
        ok = chat_services.delete_chat_session(session_id, user_name)
        if not ok:
            return BasicResponse(code=403, message="无权删除该会话", data=[])
        return BasicResponse(code=200, message="ok", data=[])
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/list")
# 获取用户的所有会话
def list_chat(user_name: str) -> BasicResponse:
    try:
        chat_records = chat_services.list_chat(user_name)
        return BasicResponse(code=200, message="ok", data=chat_records)
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/feedback")
def feedback_chat(session_id: str, message_id: int, feedback: bool) -> BasicResponse:
    try:
        chat_services.change_message_feedback(session_id, message_id, feedback)
        return BasicResponse(code=200, message="ok", data=[])
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])
