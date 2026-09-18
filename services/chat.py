"""AI 对话核心 — OpenAI Agents SDK 引擎"""

import json
import os
import logging
import time
import traceback
from typing import List, Optional

from agents import Agent, Runner, OpenAIChatCompletionsModel, ModelSettings, set_tracing_disabled
from agents.extensions.memory import AdvancedSQLiteSession
from agents.items import ToolCallOutputItem
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
from services.observability import new_request_id, request_id

logger = logging.getLogger(__name__)

# 关闭 Agents SDK 默认开启的 trace 上传。
#
# SDK 的默认行为：每次对话都把完整轨迹（含用户输入、工具调用）上传到 OpenAI 的接口，
# 并用 OPENAI_API_KEY 鉴权。而本项目的 base_url 和 key 都是第三方（DeepSeek）的，
# 上传必然失败，只留下三个副作用：
#   1. 日志刷满 [non-fatal] Tracing: request failed，把真正的报错淹掉
#   2. 进程退出时要等重试队列跑完，评测和 CI 凭空变慢
#   3. key 和对话内容被发往境外服务器（换成真实 OpenAI key 后更严重）
#
# 本项目自己的运行轨迹由 services/chat_common.py 的 append_trace() 记录，与本功能无关，
# 关掉它不影响评测。
set_tracing_disabled(True)

# 失败时的友好兜底文案：不把异常裸抛给前端，也不让记忆库留下半截工具序列
FALLBACK_MESSAGE = "抱歉，我这边出了点问题，暂时没能完成这个请求。你可以换个说法再试一次～"

async def _finalize_after_limit(client, instructions: str, session, trace: dict):
    """工具调用超限后的兜底：禁止再调工具，让模型把已获取的数据总结成回答。

    背景：原实现在超限时直接 break，而 break 跳出的是"消费模型流式事件"的循环，
    模型再也没机会生成最终回答 —— 用户只会看到一串工具调用的 JSON 加一句
    "已达上限"，一个字正文都没有（实测 8 条对话里 6 条如此）。

    做法参考 nanobot 的 finalize_on_max_iterations：预算耗尽后，
    再发一次**不带任何工具**的请求，让模型基于已有上下文作答。
    """
    summary_agent = Agent(
        name="Assistant",
        instructions=instructions,
        model=OpenAIChatCompletionsModel(
            model=os.environ["OPENAI_MODEL"],
            openai_client=client,
        ),
        model_settings=ModelSettings(temperature=0, include_usage=True),
    )
    result = Runner.run_streamed(
        summary_agent, input=BUDGET_EXHAUSTED_PROMPT, session=session
    )
    async for event in result.stream_events():
        if event.type == "raw_response_event" and hasattr(event, "data") \
                and isinstance(event.data, ResponseTextDeltaEvent):
            if event.data.delta:
                yield event.data.delta

    # 把这次兜底调用的用量累加进轨迹，否则成本统计会漏掉这一轮
    extra = _extract_usage(result)
    if extra:
        base = trace.get("usage") or {}
        trace["usage"] = {
            key: (base.get(key) or 0) + (extra.get(key) or 0)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }

def _extract_usage(result) -> dict:
    """汇总本次运行的 token 用量（用于估算成本）。取不到就返回空字典。

    两个坑：
    1. RunResultStreaming 本身没有 usage 字段 —— 用量分散在 raw_responses 里
       （每次模型调用一条），必须自己累加。
    2. 光累加还不够，得配合 ModelSettings(include_usage=True)：SDK 的默认值是
       `True if 客户端是 OpenAI else None`，也就是说用第三方 base_url 时它压根不向
       服务端索要 usage，累加出来永远是空。见 agents/models/chatcmpl_helpers.py。

    刻意写成"取不到也不报错"：token 统计是附加值，不能因为它影响对话。
    """
    try:
        responses = getattr(result, "raw_responses", None) or []
        in_tok = out_tok = total_tok = 0
        found = False
        for response in responses:
            usage = getattr(response, "usage", None)
            if usage is None:
                continue
            found = True
            in_tok += getattr(usage, "input_tokens", 0) or 0
            out_tok += getattr(usage, "output_tokens", 0) or 0
            total_tok += getattr(usage, "total_tokens", 0) or 0
        if not found:
            return {}
        return {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": total_tok or (in_tok + out_tok),
        }
    except Exception:
        logger.exception("extract usage failed")
        return {}


def _extract_tool_results(result, calls: Optional[List[dict]] = None) -> List[dict]:
    """把本轮工具返回记进轨迹，并顺手判定「空 / 错」。

    数据来源是运行结束后的 result.new_items：
      * ToolCallItem        —— 模型发起的调用
      * ToolCallOutputItem  —— 工具返回，.output 就是工具真实返回值

    名字和参数按**调用顺序**对齐，而不是靠 call_id 去配对。原因：本项目 Agent 设了
    parallel_tool_calls=False，工具是串行执行的，所以 new_items 里"第 i 个工具返回"
    必然对应调用列表里"第 i 次调用"。实测（`--id stock-01`）chat-completions 模式下
    ToolCallItem 的 raw_item 上并不总能取到 call_id，靠它配对会全是 unknown。

    和 _extract_usage 一样刻意写成"取不到也不报错"：轨迹是旁路功能，
    不能因为它影响正常对话。
    """
    try:
        items = getattr(result, "new_items", None) or []
        outputs = [item.output for item in items if isinstance(item, ToolCallOutputItem)]

        calls = calls or []
        results = []
        for index, output in enumerate(outputs):
            # 调用次数可能比返回多一条（超限那次只记录、没执行），多出来的名字用不上
            call = calls[index] if index < len(calls) else {}
            name = call.get("name", "unknown")
            text = output if isinstance(output, str) \
                else json.dumps(output, ensure_ascii=False, default=str)

            # 判定用的是**未截断**的原始返回 —— 截断后再判可能会把"只是太长"当成正常
            summary = summarize_tool_output(output)
            log_tool_result(name, call.get("args"), summary)

            results.append({
                "name": name,
                "output": truncate_for_trace(text),
                "size": summary["size"],
                "empty": summary["empty"],
                "error": summary["error"],
            })
        return results
    except Exception:
        logger.exception("extract tool results failed")
        return []


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
    # 运行轨迹：记录本轮"模型调用了哪些工具"，供离线评测使用。
    # 写在 finally 里统一落盘，确保正常结束、异常兜底、提前 return 三种情况都能留下记录。
    trace = {
        "engine": "agents",
        "question": content,
        "task": task,
        "session_id": session_id,
        "tool_calls": [],
        # 工具返回的内容（截断后）。tool_calls 只记"调了哪个工具、传了什么参数"，
        # 这里补上"工具回了什么"，离线才能核对回答里的数字有没有依据。
        "tool_results": [],
        # 本轮完整回答（含工具调用 JSON 块）。离线核对时先用 answer_body() 剥掉 JSON。
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

    # 再绑一次 session_id（值和外层一样，所以解开顺序天然正确）。
    # 为什么外层 routers/chat.py 已经绑了还要再来一次：评测脚本和测试是**直接调用**
    # chat() 的，不经过路由层 —— 不在这里兜底的话，那些场景的日志全是 [-]，
    # 而它们恰恰是最需要和 traces.jsonl 对着看的时候。
    #
    # 位置刻意贴着 try：绑在更前面（比如函数开头）的话，中间那几行一旦抛异常，
    # 下面的 finally 跑不到，session_id 就会残留在调用方的上下文里。
    request_token = request_id.set(session_id or new_request_id())

    try:
        if not tools or len(tools) == 0:
            agent = Agent(
                name="Assistant",
                instructions=instructions,
                model=OpenAIChatCompletionsModel(
                    model=os.environ["OPENAI_MODEL"],
                    openai_client=external_client,
                ),
                # temperature=0：固定采样，让同一个问题每次得到一致的工具选择。
                # 评测必须先保证"测量可靠"，否则两次跑出来的差异分不清是改动造成的还是随机波动。
                # 另一套引擎 langchain_chat.py 本来就用 temperature=0，这里对齐。
                # include_usage：第三方 base_url 下 SDK 默认不索要 token 用量，得显式打开
                model_settings=ModelSettings(parallel_tool_calls=False, temperature=0,
                                             include_usage=True),
            )
            result = Runner.run_streamed(agent, input=content, session=agent_session)
            assistant_message = ""
            async for event in result.stream_events():
                if event.type == "raw_response_event":
                    if isinstance(event.data, ResponseTextDeltaEvent):
                        if event.data.delta:
                            yield event.data.delta
                            assistant_message += event.data.delta
            trace["usage"] = _extract_usage(result)
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
                    # temperature=0：理由同上，评测要可复现（与 langchain 引擎对齐）
                    model_settings=ModelSettings(parallel_tool_calls=False, temperature=0,
                                                 include_usage=True),
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
                            trace["tool_calls"].append({
                                "name": current_tool_name,
                                "args": normalize_tool_args(event.data.item.arguments),
                            })
                            if tool_call_count > MAX_TOOL_CALLS:
                                trace["truncated"] = True
                                yield LIMIT_NOTICE
                                assistant_message += LIMIT_NOTICE
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

                trace["usage"] = _extract_usage(result)
                trace["tool_results"] = _extract_tool_results(
                    result, trace["tool_calls"]
                )
                # 超限了 → 补一次不带工具的最终回答，别让用户对着空白
                if trace["truncated"]:
                    trace["stop_reason"] = "max_tool_calls"
                    async for delta in _finalize_after_limit(
                            external_client, instructions, agent_session, trace):
                        yield delta
                        assistant_message += delta
                    if body_chars(assistant_message) == 0:
                        # 兜底也失败了：至少给一句可读的话
                        yield EMPTY_FINAL_RESPONSE_MESSAGE
                        assistant_message += EMPTY_FINAL_RESPONSE_MESSAGE
                try:
                    append_message2db(session_id, "assistant", assistant_message)
                except Exception:
                    logger.exception("failed to persist assistant message")
                schedule_memory_extraction(user_name)
    except Exception:
        logger.exception("chat run failed for session %s", session_id)
        trace["error"] = "run_failed"
        # 失败兜底：给用户一段友好文案，而不是静默/报错
        yield FALLBACK_MESSAGE
        try:
            append_message2db(session_id, "assistant", FALLBACK_MESSAGE)
        except Exception:
            logger.exception("failed to persist fallback message")
        # 清掉该会话记忆库里的残留，避免脏数据影响下一轮
        clear_agent_session_memory(session_id)
    finally:
        request_id.reset(request_token)
        trace["answer"] = assistant_message
        trace["answer_chars"] = len(assistant_message)
        trace["body_chars"] = body_chars(assistant_message)
        trace["elapsed_ms"] = int((time.perf_counter() - trace_started) * 1000)
        append_trace(trace)
