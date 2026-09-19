#!/usr/bin/env python
"""复现一次记忆提取 —— 把某用户那批未处理的消息重新喂给模型，看它到底回了什么

用法
    python eval/replay_memory.py                       # 默认用户 qq，取当前未处理的那批
    python eval/replay_memory.py --user yanzhihao
    python eval/replay_memory.py --user qq --last 8    # 只看最近 8 条消息

为什么需要它
    记忆提取是"攒够 N 条消息 → 调模型 → 解析 JSON 动作 → 落地"。
    如果解析失败，日志现在会记 `解析失败 reason=... reply_head=...`，
    但**这批消息的书签已经推过去了**（见 services/memory.py 里的说明）——
    想再看一次模型当时会回什么，就只能拿原样的消息重新跑一遍。

它只读不写：不会调 _apply_memories，也不会推进书签。
唯一的副作用是调用一次大模型（token 消耗很小：一段对话 + 一份记忆清单）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="复现一次记忆提取（只读，不写库）")
    p.add_argument("--user", default="qq", help="用户名")
    p.add_argument("--last", type=int, default=0,
                   help="取该用户最近 N 条消息，忽略书签（书签已经推过去的批次"
                        "只能这样复现）。0 表示按书签取当前未处理的那批")
    return p.parse_args()


def _recent_messages(db, user_id: int, count: int) -> list:
    """按 id 取该用户最近的 count 条 user/assistant 消息。

    为什么不复用 _unprocessed_messages：它只查 `id > 书签`，而书签一旦推过去
    就再也取不到那批消息了 —— 偏偏那种批次才最需要复现。
    """
    from models.orm import ChatMessageTable, ChatSessionTable

    rows = (
        db.query(ChatMessageTable)
        .join(ChatSessionTable, ChatSessionTable.id == ChatMessageTable.chat_id)
        .filter(
            ChatSessionTable.user_id == user_id,
            ChatMessageTable.role.in_(("user", "assistant")),
        )
        .order_by(ChatMessageTable.id.desc())
        .limit(count)
        .all()
    )
    return rows[::-1]


async def main() -> None:
    args = parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    from models.orm import SessionLocal, UserTable
    from services.memory import (
        MEMORY_BATCH_SIZE,
        _build_extract_prompt,
        _call_extract_llm,
        _parse_items,
        _read_cursor,
        _read_memories,
        _unprocessed_messages,
    )

    with SessionLocal() as db:
        user = db.query(UserTable).filter(UserTable.user_name == args.user).first()
        if user is None:
            print(f"找不到用户 {args.user}")
            return

        cursor = _read_cursor(db, user.id)
        if args.last:
            messages = _recent_messages(db, user.id, args.last)
            mode = f"最近 {args.last} 条（忽略书签）"
        else:
            messages = _unprocessed_messages(db, user.id, cursor)
            mode = "书签之后的未处理消息"

        print(f"用户            {args.user}（id={user.id}）")
        print(f"书签            {cursor}")
        print(f"取消息方式      {mode}")
        print(f"取到消息        {len(messages)} 条（提取门槛 {MEMORY_BATCH_SIZE} 条）")
        print(f"已有记忆        {len(_read_memories(db, user.id))} 条")

        if not messages:
            print("\n没有未处理的消息 —— 说明书签已经推到最新，没什么可复现的。")
            return
        if len(messages) < MEMORY_BATCH_SIZE:
            print(f"\n注意：不足 {MEMORY_BATCH_SIZE} 条，真实流程会跳过不调模型。"
                  "这里仍然照跑，方便看模型会给什么。")

        print("\n--- 这批消息 ---")
        for m in messages:
            text = (m.content or "").replace("\n", " ")[:110]
            print(f"  [{m.role}] {text}")

        prompt = _build_extract_prompt(_read_memories(db, user.id), messages)

    print(f"\n--- 提示词 {len(prompt)} 字符，调用模型中…… ---")
    reply = await _call_extract_llm(prompt)

    print(f"\n--- 模型回复（{len(reply or '')} 字符）---")
    print(reply)

    items, error = _parse_items(reply)
    print("\n--- 解析结果 ---")
    if error:
        print(f"❌ 失败: {error}")
        print("   ↑ 这就是原来被记成「extracted 0 item(s)」、和「没什么可记」"
              "混在一起的那种情况")
    elif items:
        print(f"✅ 成功，提取 {len(items)} 条：")
        for it in items:
            print(f"   - {it}")
    else:
        print("✅ 成功，但模型认为本批无可记（回了空数组）—— 这是正常结果")


if __name__ == "__main__":
    asyncio.run(main())
