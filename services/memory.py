"""用户级长期记忆：跨会话记住用户的偏好/事实。

设计（参考 nanobot 的异步批量沉淀思路）：
1. 历史本来就在 chat_message 表里，不需要额外存储；
2. 每次对话结束后，后台任务检查该用户"上次处理到哪条消息"（游标）；
3. 未处理的新消息攒够 MEMORY_BATCH_SIZE（默认 10）条才调一次模型，
   把这段对话 + 已有记忆清单喂给模型，输出更新后的记忆 JSON，upsert 进 user_memory；
4. 游标就存在 user_memory 表里一条 key='__cursor__' 的特殊记录（注入时跳过）；
5. get_memory_section() 供 get_init_message 注入「用户长期记忆」段落（两个引擎共用）。
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import List, Optional

from models.orm import (
    SessionLocal,
    UserTable,
    UserMemoryTable,
    ChatSessionTable,
    ChatMessageTable,
)

logger = logging.getLogger(__name__)

MEMORY_ENABLED = os.environ.get("MEMORY_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")  # 支持 1/true/yes/on 作为开启，默认开启记忆功能。
MEMORY_BATCH_SIZE = int(os.environ.get("MEMORY_BATCH_SIZE", "10"))  # 攒够多少条未处理消息才提取
MEMORY_MAX_ITEMS = int(os.environ.get("MEMORY_MAX_ITEMS", "30"))   # 每个用户最多保留多少条记忆
MEMORY_MODEL = os.environ.get("MEMORY_MODEL", "")                  # 提取用模型，默认同主模型
MEMORY_MESSAGE_CAP = 60                                            # 单次提取最多携带多少条消息
MEMORY_CONTENT_MAX = 300                                           # 每条记忆最长字符数

CURSOR_KEY = "__cursor__"

# 持有后台任务的引用，防止被 GC 回收
_background_tasks: set = set()


def _read_cursor(db, user_id: int) -> int:  # 读"上次处理到第几条消息"
    row = db.query(UserMemoryTable).filter(
        UserMemoryTable.user_id == user_id,
        UserMemoryTable.key == CURSOR_KEY,
    ).first()
    if row is None:
        return 0
    try:
        return int(row.content)
    except (TypeError, ValueError):
        return 0


def _write_cursor(db, user_id: int, cursor: int) -> None: # 写游标（书签）
    row = db.query(UserMemoryTable).filter(
        UserMemoryTable.user_id == user_id,
        UserMemoryTable.key == CURSOR_KEY,
    ).first()
    if row:
        row.content = str(cursor)
        row.updated_at = datetime.utcnow()
    else:
        db.add(UserMemoryTable(user_id=user_id, key=CURSOR_KEY, content=str(cursor)))


def _unprocessed_messages(db, user_id: int, cursor: int) -> List[ChatMessageTable]: # 查该用户游标之后的新消息
    """返回该用户 id > cursor 的 user/assistant 消息（最多 MEMORY_MESSAGE_CAP 条）。"""
    return (
        db.query(ChatMessageTable)
        .join(ChatSessionTable, ChatSessionTable.id == ChatMessageTable.chat_id)
        .filter(
            ChatSessionTable.user_id == user_id,
            ChatMessageTable.id > cursor,
            ChatMessageTable.role.in_(("user", "assistant")),
        )
        .order_by(ChatMessageTable.id.asc())
        .limit(MEMORY_MESSAGE_CAP)
        .all()
    )


def _read_memories(db, user_id: int) -> List[str]: # 读取用户的"长期记忆"
    rows = db.query(UserMemoryTable).filter(
        UserMemoryTable.user_id == user_id,
        UserMemoryTable.key != CURSOR_KEY, # 排除系统内部记忆（__cursor__）
    ).order_by(UserMemoryTable.updated_at.desc()).all()
    # 带上 key，让模型能按 key 做 update/delete
    return [f"- {r.key}: {r.content}" for r in rows]


def _build_extract_prompt(existing: List[str], messages: List[ChatMessageTable]) -> str: # 组提取提示词（优先级+句式+三动作）
    history_lines = []
    for m in messages[-40:]:
        text = (m.content or "").replace("\n", " ")[:200]
        history_lines.append(f"[{m.role}] {text}")
    existing_text = "\n".join(existing) if existing else "（暂无记忆）"
    return f"""你是一个用户长期记忆管理助手。根据最近对话，维护该用户的长期记忆（身份、偏好、持仓、习惯等）。

## 提取优先级（从高到低）
1. 用户身份与偏好：姓名、城市、职业、持仓股票、关注板块、回答风格、沟通习惯——只要用户明确表达，必须提取或更新。
2. 稳定的生活/项目事实（如用户在用什么技术栈、常用工具）。
3. 一次性话题、临时状态、闲聊、网上可查的信息——不要记。

## 句式识别（重要）
用户表达持有/持仓/关注某标的或板块（如"我持有深圳华强"、"我持仓 XXX"、"我关注新能源板块"），
以及助手已确认的用户持仓（如"你是深圳华强的持仓股东"）→ 必须提取，记偏好。
用户说"我喜欢简洁回答"、"我在北京工作" → 记偏好/身份。

## 输出格式
输出 JSON 数组，每项是一个动作：
- 新增/更新：{{"action": "add" 或 "update", "key": "简短标签（2~8个字）", "content": "一句原子事实"}}
- 删除过时记忆：{{"action": "delete", "key": "要删除的记忆标签"}}

规则：
1. 与现有记忆同 key 且有新信息 → 用 update（或 add，同 key 会覆盖旧内容）。
2. 用户明确推翻旧记忆（如"我不在深圳了""我把深圳华强卖了""我不喜欢简洁回答了"）→ 输出 delete 对应 key，或 update 为新内容。
3. 没有值得记的 → 输出 []。
4. 只输出 JSON，不要输出任何其他文字。

该用户当前的长期记忆清单（key 用于 update/delete 定位）：
{existing_text}

最近对话记录：
{chr(10).join(history_lines)}

请输出 JSON："""


async def _call_extract_llm(prompt: str) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )
    model = MEMORY_MODEL or os.environ["OPENAI_MODEL"]
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是用户长期记忆提取助手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    return resp.choices[0].message.content or ""


def _parse_items(reply: str) -> List[dict]: # 解析模型输出的 JSON 动作
    text = (reply or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text) # 清洗原始文本 去掉 Markdown 代码块标记
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start: #无效
        return []
    try:
        items = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    result: List[dict] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        action = str(it.get("action") or "add").strip().lower() # 提取 action 字段
        key = str(it.get("key") or "").strip()[:50]
        if action == "delete":
            if key:
                result.append({"action": "delete", "key": key})
            continue
        content = str(it.get("content") or "").strip()[:MEMORY_CONTENT_MAX]
        if key and content:
            result.append({"action": "add", "key": key, "content": content})
    return result


def _apply_memories(db, user_id: int, items: List[dict]) -> None: # 核心：add/update/delete 落地
    for it in items:
        if it.get("action") == "delete":
            db.query(UserMemoryTable).filter(
                UserMemoryTable.user_id == user_id,
                UserMemoryTable.key == it["key"],
            ).delete(synchronize_session=False)
            continue
        row = db.query(UserMemoryTable).filter(
            UserMemoryTable.user_id == user_id,
            UserMemoryTable.key == it["key"],
        ).first()
        if row:
            row.content = it["content"]
            row.updated_at = datetime.utcnow()
        else:
            db.add(UserMemoryTable(user_id=user_id, key=it["key"], content=it["content"]))

    # 超过上限时删除最旧的（游标行保留） 记忆总数超限
    count = db.query(UserMemoryTable).filter(
        UserMemoryTable.user_id == user_id,
        UserMemoryTable.key != CURSOR_KEY,
    ).count()
    if count > MEMORY_MAX_ITEMS:
        extra = count - MEMORY_MAX_ITEMS
        old_rows = db.query(UserMemoryTable).filter(
            UserMemoryTable.user_id == user_id,
            UserMemoryTable.key != CURSOR_KEY,
        ).order_by(UserMemoryTable.updated_at.asc()).limit(extra).all()
        for r in old_rows:
            db.delete(r)


async def extract_user_memory(user_name: str) -> None: # 主流程：把上面全串起来（攒够→调模型→应用→推进书签）
    """后台任务：批量提取该用户的新对话记忆。"""
    if not MEMORY_ENABLED:
        return
    try:
        with SessionLocal() as db:
            user = db.query(UserTable).filter(UserTable.user_name == user_name).first()
            if user is None:
                return
            cursor = _read_cursor(db, user.id)
            messages = _unprocessed_messages(db, user.id, cursor)
            if len(messages) < MEMORY_BATCH_SIZE:
                logger.info(
                    "memory: user %s only %d new message(s) (< %d), skip",
                    user_name, len(messages), MEMORY_BATCH_SIZE,
                )
                return
            existing = _read_memories(db, user.id)
            prompt = _build_extract_prompt(existing, messages)
            reply = await _call_extract_llm(prompt)
            items = _parse_items(reply)
            if items:
                _apply_memories(db, user.id, items)
            _write_cursor(db, user.id, messages[-1].id)
            db.commit()
            logger.info(
                "memory: user %s extracted %d item(s), cursor -> %d",
                user_name, len(items), messages[-1].id,
            )
    except Exception:
        logger.exception("memory extraction failed for %s", user_name)


def schedule_memory_extraction(user_name: str) -> None: # 起后台任务（不阻塞回答）
    """对话成功后调用：在后台触发一次记忆提取（不阻塞回答）。"""
    if not MEMORY_ENABLED or not user_name:
        return
    try:
        task = asyncio.create_task(extract_user_memory(user_name)) # asyncio.create_task() 创建一个异步任务
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard) # 完成后，自动清理任务
    except RuntimeError:
        logger.exception("no running event loop for memory extraction")


def get_memory_section(user_name: Optional[str]) -> str: # 生成注入段落 生成一段"用户长期记忆"的文本，用于注入到系统提示词中。
    """注入用：返回该用户的长期记忆文本段（没有则为空串）。"""
    if not MEMORY_ENABLED or not user_name:
        return ""
    try:
        with SessionLocal() as db:
            user = db.query(UserTable).filter(UserTable.user_name == user_name).first()
            if user is None:
                return ""
            rows = db.query(UserMemoryTable).filter(
                UserMemoryTable.user_id == user.id,
                UserMemoryTable.key != CURSOR_KEY,
            ).order_by(UserMemoryTable.updated_at.desc()).all()
            if not rows:
                return ""
            lines = [f"- {r.content}" for r in rows]
            return "## 用户长期记忆\n" + "\n".join(lines)
    except Exception:
        logger.exception("failed to build memory section for %s", user_name)
        return ""
