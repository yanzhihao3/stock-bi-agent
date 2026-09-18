"""AI 对话路由（JWT 认证版 + SSE 流式协议）

- 所有接口都要求登录，用户身份统一从 token 解析
- 聊天接口使用标准 SSE（text/event-stream）：正文为 message 事件，异常为 error 事件
- 流式生成器内部捕获异常，避免连接被直接掐断、用户只看到半截回答
"""

import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

import services.chat as chat_agents
import services.chat_common as chat_common
import services.langchain_chat as chat_langchain
from agents import set_default_openai_api, set_tracing_disabled
from models.data_models import BasicResponse, RequestForChat
from models.orm import UserTable
from services.auth import get_current_user
from services.errors import BusinessError
from services.observability import request_id

set_default_openai_api("chat_completions")
set_tracing_disabled(True)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/chat", tags=["chat"])


def _ok(data=None, message: str = "ok") -> BasicResponse:
    return BasicResponse(code=200, message=message, data=data)


@router.post("/")
async def chat(
    req: RequestForChat,
    user: UserTable = Depends(get_current_user),
) -> StreamingResponse:
    """流式聊天：正文按 message 事件逐段下发，异常按 error 事件下发"""

    async def chat_stream_generator():
        # 一次聊天的关联键用 session_id：日志、运行轨迹、数据库三边都能对上这个值，
        # 排查时 grep 一个 session_id 就能捞出从接口到模型到工具的完整链路。
        #
        # 绑在这里而不是 services/chat.py 内部：异步生成器里的 ContextVar
        # set/reset 跨 yield 时行为很绕，绑在调用方（这里）最稳。已用探针验证：
        # 生成器里 set 的 id 能被内层引擎生成器里的 logger 看到，并发也不串号。
        token = request_id.set(req.session_id)
        try:
            engine = chat_langchain if req.engine == "langchain" else chat_agents
            async for chunk in engine.chat(
                user_name=user.user_name,
                task=req.task,
                session_id=req.session_id,
                content=req.content,
                tools=req.tools,
            ):
                if chunk:
                    yield chat_common.sse_event("message", {"content": chunk})
        except asyncio.CancelledError:
            # 客户端主动断开（关闭页面/停止请求），静默结束，不算服务端错误
            raise
        except Exception:
            # 流式执行中途出错：HTTP 状态码和响应头已发出，无法再返回错误 JSON，
            # 只能向客户端发送 error 事件，服务端记录完整堆栈。
            logger.exception("chat stream failed")
            error_message = "回答生成失败，请稍后重试"
            yield chat_common.sse_event("error", {"code": 500, "message": error_message})
            try:
                # 把错误提示持久化，保证会话历史完整
                chat_common.append_message2db(
                    req.session_id, "assistant", f"[系统提示] {error_message}"
                )
            except Exception:
                logger.exception("failed to persist chat error message")
        finally:
            request_id.reset(token)

    return StreamingResponse(
        content=chat_stream_generator(),
        media_type="text/event-stream",
    )


@router.post("/init")
async def init_chat(user: UserTable = Depends(get_current_user)) -> BasicResponse:
    return _ok({"session_id": chat_common.generate_random_chat_id()})


@router.post("/get")
def get_chat(
    session_id: str,
    user: UserTable = Depends(get_current_user),
) -> BasicResponse:
    """获取会话历史，仅允许会话所属用户访问"""
    response = chat_common.get_chat_sessions(session_id, user.user_name)
    if response is None:
        raise BusinessError(403, "无权查看该会话")
    return _ok(response)


@router.post("/delete")
def delete_chat(
    session_id: str,
    user: UserTable = Depends(get_current_user),
) -> BasicResponse:
    """删除会话，仅允许会话所属用户操作"""
    if not chat_common.delete_chat_session(session_id, user.user_name):
        raise BusinessError(403, "无权删除该会话")
    return _ok(message="删除成功")


@router.post("/list")
def list_chat(user: UserTable = Depends(get_current_user)) -> BasicResponse:
    """列出当前登录用户的会话列表"""
    return _ok(chat_common.list_chat(user.user_name))


@router.post("/feedback")
def feedback_chat(
    session_id: str,
    message_id: int,
    feedback: bool,
    user: UserTable = Depends(get_current_user),
) -> BasicResponse:
    """对会话内某条消息打反馈"""
    chat_common.change_message_feedback(session_id, message_id, feedback)
    return _ok(message="反馈成功")
