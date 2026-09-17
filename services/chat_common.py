"""AI 对话公共模块 — 被 agents 和 langchain 两个引擎共用"""

import hashlib
import json
import logging
import os
import random
import sqlite3
import string
import time
from datetime import datetime
from functools import wraps
from typing import List, Dict, Any, Optional

from jinja2 import Environment, FileSystemLoader

from models.orm import ChatSessionTable, ChatMessageTable, SessionLocal, UserTable
from models.data_models import ChatSession
from services.memory import get_memory_section

logger = logging.getLogger(__name__)

TIMESTAMP_SECRET = os.environ.get("TIMESTAMP_SECRET", "default_secret_change_in_production")

MAX_HISTORY_MESSAGES = 20  # 双引擎共享：多轮上下文滑窗条数，超出丢弃最老

AGENT_DB_PATH = "./assert/conversations.db"


# 运行轨迹文件：一行一条 JSON，供离线评测「模型是否选对了工具」使用。
# 可用环境变量 TRACE_PATH 覆盖（评测脚本用它隔离每次跑批的记录）。
TRACE_PATH = os.environ.get("TRACE_PATH", "./logs/traces.jsonl")


def append_trace(record: Dict[str, Any]) -> None:
    """把一次对话的运行轨迹追加到 JSONL 文件。

    设计上有三点考虑：
    1. 只追加、不改动、不读取，天然适合并发写入，也方便事后逐行分析；
    2. 内部吞掉所有异常 —— 记录轨迹失败绝不能影响正常对话；
    3. 记录的是「模型调用了哪些工具」，而不是工具返回了什么，
       所以第三方接口挂了、限流了、甚至断网，都不影响评测结论。

    两个引擎（Agents SDK / LangChain）共用这一个函数。
    """
    try:
        directory = os.path.dirname(TRACE_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        record.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        with open(TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # 刻意不抛出：轨迹记录是旁路功能，不能因为它让对话失败
        logger.exception("append_trace failed")


def normalize_tool_args(raw: Any) -> Any:
    """把工具调用参数统一成「对象」形式，再落盘。

    踩过的坑：两个引擎给出的原始格式不一致 ——
      * Agents SDK 的 ResponseFunctionToolCall.arguments 是 JSON 字符串
      * LangChain 的 on_tool_start 事件给的是 dict
    原样存储的话，评测脚本就得写两套解析逻辑，还容易埋出"某个引擎的参数永远比对不上"
    这种不报错却静默失真的问题。这里统一：能解析成 JSON 就转成对象，否则原样返回。
    """
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def clear_agent_session_memory(session_id: Optional[str]) -> None:
    """清空某个会话在 Agents SDK 记忆库（conversations.db）里的4 张表记录全部记录。

    删除会话/删除用户时必须一并调用，否则 conversations.db 里会残留孤儿数据。
    """
    if not session_id:
        return
    try:
        conn = sqlite3.connect(AGENT_DB_PATH, timeout=10)
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM agent_messages WHERE session_id = ?", (session_id,))
            cur.execute("DELETE FROM message_structure WHERE session_id = ?", (session_id,))
            cur.execute("DELETE FROM turn_usage WHERE session_id = ?", (session_id,))
            cur.execute("DELETE FROM agent_sessions WHERE session_id = ?", (session_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("failed to clear agent session memory for %s", session_id)

TOOL_CATEGORIES = {
    "股票分析": ["stock_get_codes", "stock_get_index_code", "stock_get_industry_code",
                "stock_get_board_info", "stock_get_rank", "stock_get_month_line",
                "stock_get_week_line", "stock_get_day_line", "stock_get_info", "stock_get_minute_data"],
    "新闻聚合": ["get_today_daily_news", "get_douyin_hot_news", "get_github_hot_news",
                "get_toutiao_hot_news", "get_sports_news"],
    "通用工具": ["get_city_weather", "get_address_detail", "get_tel_info",
                "get_scenic_info", "get_flower_info", "get_rate_transform"],
    "名言鸡汤": ["get_today_familous_saying", "get_today_motivation_saying", "get_today_working_saying"],
}

TASK_TO_CATEGORIES = {
    "股票分析": ["股票分析"],
    "数据BI": ["股票分析", "通用工具"],
    "通用聊天": ["名言鸡汤"],
}


def sse_event(event: str, data: dict) -> str:
    """构造 SSE 事件帧，格式：event: <type>\ndata: <json>\n\n

    聊天流式接口统一用 SSE 传输：正文走 message 事件，异常走 error 事件，
    前端按事件类型区分渲染，避免把错误提示当成正文展示。
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def get_category_tools(category: str) -> List[str]:
    return TOOL_CATEGORIES.get(category, [])


def suggest_categories(task: Optional[str]) -> List[str]:
    if not task:
        return list(TOOL_CATEGORIES.keys())
    return TASK_TO_CATEGORIES.get(task, list(TOOL_CATEGORIES.keys()))


def with_retry(max_retries: int = 3, base_delay: float = 1.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


def generate_random_chat_id(length=12) -> str:
    with SessionLocal() as session:
        for retry_time in range(20):
            characters = string.ascii_letters + string.digits
            session_id = ''.join(random.choice(characters) for _ in range(length))
            chat_session_record: ChatSessionTable | None = session.query(ChatSessionTable).filter(
                ChatSessionTable.session_id == session_id).first()
            if chat_session_record is None:
                break
            if retry_time > 10:
                raise Exception("Failed to generate a unique session_hash")
    return session_id


def get_init_message(task: str, user_name: Optional[str] = None) -> str:
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("chat_start_system_prompt.jinja2")

    if task == "股票分析":
        task_description = """
1. 专注于全球主要股票市场（如 NYSE, NASDAQ, SHSE, HKEX）的分析。
2. 必须使用专业、严谨的金融术语，如 P/E, EPS, Beta, ROI, 护城河 (Moat) 等。
3. **在提供分析时，必须清晰地说明数据来源、分析模型的局限性，并强调你的意见不构成最终的投资建议。**
4. 仅基于公开市场数据和合理的财务假设进行分析，禁止进行内幕交易或非公开信息的讨论。
5. 结果要求：提供结构化的分析（如：公司概览、财务健康度、估值模型、风险与机遇）。
"""
    elif task == "数据BI":
        task_description = """
1. 帮助用户理解他们的数据结构、商业指标和关键绩效指标 (KPI)。
2. 用户的请求通常是数据查询、指标定义或图表生成建议。
3. **关键约束：你的输出必须是可执行的代码块 (如 SQL 或 Python)，或者清晰的逻辑步骤，用于解决用户的数据问题。**
4. 严格遵守数据分析的逻辑严谨性，确保每一个结论都有数据支撑。
5. 当被要求提供可视化建议时，请推荐最合适的图表类型（如：时间序列用折线图，分类对比用柱状图）。"""
    else:
        task_description = """
1. 保持对话的自然和流畅，以轻松愉快的语气回应用户。
2. 避免过于专业或生硬的术语，除非用户明确要求。
3. 倾听用户的表达，并在适当的时候提供支持、鼓励或趣味性的知识。
4. 确保回答简洁，富有情感色彩，不要表现得像一个没有感情的机器。
5. 关键词：友好、轻松、富有同理心。
        """
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    signature = hashlib.sha256((timestamp_str + TIMESTAMP_SECRET).encode()).hexdigest()[:16]
    system_prompt = template.render(
        agent_name="小呆助手",
        task_description=task_description,
        current_datetime=now.strftime("%Y-%m-%d %H:%M:%S"),
        timestamp_signature=signature,
    )
    # 注入用户长期记忆（两个引擎共用这一处）
    memory_section = get_memory_section(user_name)
    if memory_section:
        system_prompt = system_prompt.rstrip() + "\n\n" + memory_section
    return system_prompt


def init_chat_session(user_name: str, user_question: str, session_id: str, task: str) -> None:
    with SessionLocal() as session:
        user_id = session.query(UserTable.id).filter(UserTable.user_name == user_name).first()
        chat_session_record = ChatSessionTable(
            user_id=user_id[0],
            session_id=session_id,
            title=user_question,
        )
        session.add(chat_session_record)
        session.commit()
        session.flush()

        message_record = ChatMessageTable(
            chat_id=chat_session_record.id,
            role="system",
            content=get_init_message(task, user_name),
        )
        session.add(message_record)
        session.flush()
        session.commit()


def append_message2db(session_id: str, role: str, content: str) -> None:
    with SessionLocal() as session:
        chat_record = session.query(ChatSessionTable.id).filter(
            ChatSessionTable.session_id == session_id).first()
        if chat_record:
            message_record = ChatMessageTable(
                chat_id=chat_record[0],
                role=role,
                content=content,
            )
            session.add(message_record)
            session.commit()


def get_chat_sessions(session_id: str, user_name: str) -> Optional[List[Dict[str, Any]]]:
    with SessionLocal() as session:
        record: Optional[ChatSessionTable] = session.query(ChatSessionTable).filter(
            ChatSessionTable.session_id == session_id).first()
        if record is None:
            return None
        if record.user_id is None:
            return None
        user = session.query(UserTable).filter(UserTable.id == record.user_id).first()
        if user is None or user.user_name != user_name:
            return None

        chat_messages: Optional[List[ChatMessageTable]] = session.query(ChatMessageTable) \
            .join(ChatSessionTable) \
            .filter(ChatSessionTable.session_id == session_id).all()

        result = []
        if chat_messages:
            for record in chat_messages:
                result.append({
                    "id": record.id, "create_time": record.create_time,
                    "feedback": record.feedback, "feedback_time": record.feedback_time,
                    "role": record.role, "content": record.content,
                })
        return result


def delete_chat_session(session_id: str, user_name: str) -> bool:
    with SessionLocal() as session:
        record: Optional[ChatSessionTable] = session.query(ChatSessionTable).filter(
            ChatSessionTable.session_id == session_id).first()
        if record is None:
            return False
        if record.user_id is None:
            return False
        user = session.query(UserTable).filter(UserTable.id == record.user_id).first()
        if user is None or user.user_name != user_name:
            return False

        session.query(ChatMessageTable).where(ChatMessageTable.chat_id == record.id).delete()
        session.query(ChatSessionTable).where(ChatSessionTable.id == record.id).delete()
        session.commit()
        # 顺手清掉该会话在 AI 记忆库里的记录，避免孤儿数据
        clear_agent_session_memory(session_id)
        return True


def change_message_feedback(session_id: str, message_id: int, feedback: bool) -> bool:
    with SessionLocal() as session:
        id_ = session.query(ChatSessionTable.id).filter(
            ChatSessionTable.session_id == session_id).first()
        if id_ is None:
            return False
        record = session.query(ChatMessageTable).filter(
            ChatMessageTable.id == message_id,
            ChatMessageTable.chat_id == id_[0]).first()
        if record is not None:
            record.feedback = feedback
            record.feedback_time = datetime.now()
            session.commit()
        return True


def list_chat(user_name: str) -> Optional[List[Any]]:
    with SessionLocal() as session:
        user_id = session.query(UserTable.id).filter(UserTable.user_name == user_name).first()
        if user_id:
            chat_records: Optional[List[ChatSessionTable]] = session.query(
                ChatSessionTable.user_id,
                ChatSessionTable.session_id,
                ChatSessionTable.title,
                ChatSessionTable.start_time,
            ).filter(ChatSessionTable.user_id == user_id[0]).all()
            if chat_records:
                return [ChatSession(
                    user_id=x.user_id, session_id=x.session_id,
                    title=x.title, start_time=x.start_time) for x in chat_records]
            else:
                return []
        else:
            return []
