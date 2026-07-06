"""AI 对话公共模块 — 被 agents 和 langchain 两个引擎共用"""

import hashlib
import os
import random
import string
import time
from datetime import datetime
from functools import wraps
from typing import List, Dict, Any, Optional

from jinja2 import Environment, FileSystemLoader

from models.orm import ChatSessionTable, ChatMessageTable, SessionLocal, UserTable
from models.data_models import ChatSession

TIMESTAMP_SECRET = os.environ.get("TIMESTAMP_SECRET", "default_secret_change_in_production")

TOOL_CATEGORIES = {
    "股票分析": ["stock_get_codes", "stock_get_index_code", "stock_get_industry_code",
                "stock_get_board_info", "stock_get_rank", "stock_get_month_line",
                "stock_get_week_line", "stock_get_day_line", "stock_get_info", "stock_get_minute_data"],
    "新闻聚合": ["get_today_daily_news", "get_douyin_hot_news", "get_github_hot_news",
                "get_toutiao_hot_news", "get_sports_news"],
    "通用工具": ["get_city_weather", "get_address_detail", "get_tel_info",
                "get_flower_info", "get_rate_transform"],
    "名言鸡汤": ["get_today_familous_saying", "get_today_motivation_saying", "get_today_working_saying"],
}

TASK_TO_CATEGORIES = {
    "股票分析": ["股票分析"],
    "数据BI": ["股票分析", "通用工具"],
    "通用聊天": ["名言鸡汤"],
}


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


def get_init_message(task: str) -> str:
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
            content=get_init_message(task),
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
