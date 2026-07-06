import traceback

from fastapi import FastAPI, APIRouter
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

import services.chat as chat_agents
import services.langchain_chat as chat_langchain
import services.chat_common as chat_common
from models.data_models import BasicResponse, RequestForChat
from agents import set_default_openai_api, set_tracing_disabled

set_default_openai_api("chat_completions")
set_tracing_disabled(True)

router = APIRouter(prefix="/v1/chat", tags=["chat"])


@router.post("/")
async def chat(req: RequestForChat) -> StreamingResponse:
    try:
        async def chat_stream_generator():
            if req.engine == "langchain":
                async for chunk in chat_langchain.chat(
                    user_name=req.user_name,
                    task=req.task,
                    session_id=req.session_id,
                    content=req.content,
                    tools=req.tools,
                ):
                    yield chunk
            else:
                async for chunk in chat_agents.chat(
                    user_name=req.user_name,
                    task=req.task,
                    session_id=req.session_id,
                    content=req.content,
                    tools=req.tools,
                ):
                    yield chunk

        return StreamingResponse(
            content=chat_stream_generator(),
            media_type="text/event-stream",
        )
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/init")
async def init_chat() -> BasicResponse:
    try:
        return BasicResponse(
            code=200, message="ok",
            data={"session_id": chat_common.generate_random_chat_id()},
        )
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/get")
def get_chat(session_id: str, user_name: str) -> BasicResponse:
    try:
        response = chat_common.get_chat_sessions(session_id, user_name)
        if response is None:
            return BasicResponse(code=403, message="无权查看该会话", data=[])
        return BasicResponse(code=200, message="ok", data=response)
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/delete")
def delete_chat(session_id: str, user_name: str) -> BasicResponse:
    try:
        ok = chat_common.delete_chat_session(session_id, user_name)
        if not ok:
            return BasicResponse(code=403, message="无权删除该会话", data=[])
        return BasicResponse(code=200, message="ok", data=[])
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/list")
def list_chat(user_name: str) -> BasicResponse:
    try:
        chat_records = chat_common.list_chat(user_name)
        return BasicResponse(code=200, message="ok", data=chat_records)
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])


@router.post("/feedback")
def feedback_chat(session_id: str, message_id: int, feedback: bool) -> BasicResponse:
    try:
        chat_common.change_message_feedback(session_id, message_id, feedback)
        return BasicResponse(code=200, message="ok", data=[])
    except Exception as e:
        print(traceback.format_exc())
        return BasicResponse(code=500, message=traceback.format_exc(), data=[])
