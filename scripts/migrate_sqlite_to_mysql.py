#!/usr/bin/env python
"""把业务库从 SQLite 迁到 MySQL（一次性脚本，可重复运行）

用法
    python scripts/migrate_sqlite_to_mysql.py --check   # 只看两边行数，不写任何东西
    python scripts/migrate_sqlite_to_mysql.py           # 真的迁

前提（三条都要满足）
    1. `.env` 里配好了 DATABASE_URL，指向 MySQL
    2. MySQL 那边的表已经建好：先跑一次 `python -c "import models.orm"`
    3. 目标库是空的（脚本会检查，不空就拒绝执行，除非加 --force）

安全设计
    * **源库永远是只读的** —— 全程只 SELECT，不动 assert/sever.db 一个字节
    * DATABASE_URL 不是 MySQL 时直接拒绝运行（防止误把 SQLite 当目标、自己覆盖自己）
    * 目标表已有数据时拒绝运行（默认），避免重复插入出一堆重复行；确需重来用 --reset
    * 按外键依赖顺序插入；插完核对两边行数

它不迁的东西
    Agents SDK 的记忆库 `assert/conversations.db`（agent_sessions / agent_messages /
    message_structure / turn_usage）**不迁**。那是 SDK 自带的 SQLite 实现，表结构
    不受本项目控制，换也换不动。会话记忆继续留在本地那个文件里。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 插入顺序必须满足外键依赖：
#   user  →  chat_session  →  chat_message（chat_id 指向 chat_session）
#         →  user_memory / user_favorite_stock / data（user_id 指向 user）
TABLE_ORDER = ("user", "chat_session", "chat_message", "user_memory",
               "user_favorite_stock", "data")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SQLite → MySQL 数据迁移")
    p.add_argument("--check", action="store_true", help="只核对行数，不写数据")
    p.add_argument("--reset", action="store_true",
                   help="先按反向外键顺序清空目标表再迁（半途失败后重来用这个）")
    p.add_argument("--force", action="store_true",
                   help="目标表已有数据时也照插（会产生重复行，慎用）")
    p.add_argument("--sqlite", default=str(ROOT / "assert" / "sever.db"),
                   help="源库路径（默认 assert/sever.db，只读）")
    return p.parse_args()


def q(name: str) -> str:
    """反引号包住标识符。

    ⚠️ 这个不是可有可无的洁癖，是真踩过的坑：`user_memory.key` 里的 key 是
    MySQL 的**保留字**（SQLite 不保留），不加引号的
        INSERT INTO user_memory (id, user_id, key, ...)
    会直接报 1064 语法错误。第一次迁移就挂在这上面。

    反引号在 SQLite 里也是合法的标识符引用写法，所以两边都能用同一个函数。
    （应用代码不用操心这个：SQLAlchemy ORM 会自动给保留字加引号，实测通过。）
    """
    return f"`{name}`"


def main() -> None:
    args = parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    target = os.environ.get("DATABASE_URL", "")
    if not target:
        sys.exit("[中断] .env 里没有 DATABASE_URL —— 没配的话代码会走 SQLite，"
                 "这个脚本就没有意义了。")
    if target.startswith("sqlite"):
        sys.exit(f"[中断] DATABASE_URL 指向的还是 SQLite（{target}）。\n"
                 "       这个脚本是往 MySQL 迁的，请先把它改成 "
                 "mysql+pymysql://... 再运行。")

    from sqlalchemy import create_engine, inspect, text

    source_path = Path(args.sqlite)
    if not source_path.exists():
        sys.exit(f"[中断] 找不到源库：{source_path}")

    src = create_engine(f"sqlite:///{source_path.as_posix()}")
    dst = create_engine(target, pool_pre_ping=True)

    # 前置检查：目标库的表建好了没、是不是空的
    existing = set(inspect(dst).get_table_names())
    missing = [t for t in TABLE_ORDER if t not in existing]
    if missing:
        sys.exit(f"[中断] 目标库缺这些表：{missing}\n"
                 '       先跑一次 `python -c "import models.orm"` 建表。')

    def count(engine, table: str) -> int:
        with engine.connect() as conn:
            return conn.execute(text(f"SELECT COUNT(*) FROM {q(table)}")).scalar() or 0

    print(f"源库   {source_path}（只读）")
    print(f"目标   {target.split('@')[-1]}")   # 只打 host/db，避免把密码打出来
    print()
    print(f"{'表':<22}{'源库':>8}{'目标库':>10}")
    print("-" * 40)

    occupied = []
    for table in TABLE_ORDER:
        n_src, n_dst = count(src, table), count(dst, table)
        if n_dst:
            occupied.append((table, n_dst))
        print(f"{table:<22}{n_src:>8}{n_dst:>10}")

    if args.check:
        print("\n（--check 模式：只核对，没写任何数据）")
        return

    if args.reset and occupied:
        # 半途失败后必须这样重来：直接重跑会撞上"目标表已有数据"的拦截，
        # 加 --force 又会在 user / chat_session / chat_message 上插出重复行。
        # 所以按**反向外键顺序**（先子后父）清空，再从头迁。
        print("\n--reset：先清空目标库这几张表（按反向外键顺序）")
        with dst.begin() as conn:
            for table in reversed(TABLE_ORDER):
                n = conn.execute(text(f"SELECT COUNT(*) FROM {q(table)}")).scalar() or 0
                if n:
                    conn.execute(text(f"DELETE FROM {q(table)}"))
                    print(f"  已清空 {table:<22} 原 {n} 行")
        occupied = []

    if occupied and not args.force:
        detail = "、".join(f"{t}({n} 行)" for t, n in occupied)
        sys.exit(f"\n[中断] 目标库这些表已经有数据：{detail}\n"
                 "       直接插会产生重复行。确认过再运行就加 --force；"
                 "半途失败想重来用 --reset；"
                 "或者先把目标表清空。")

    inserted = 0
    for table in TABLE_ORDER:
        with src.connect() as conn:
            rows = [dict(r) for r in conn.execute(text(f"SELECT * FROM {q(table)}")).mappings()]
        if not rows:
            continue
        columns = list(rows[0])
        stmt = text(
            f"INSERT INTO {q(table)} ({', '.join(q(c) for c in columns)}) "
            f"VALUES ({', '.join(':' + c for c in columns)})"
        )
        with dst.begin() as conn:
            conn.execute(stmt, rows)
        inserted += len(rows)
        print(f"  已写入 {table:<22} {len(rows):>4} 行")

    print(f"\n合计写入 {inserted} 行。核对一下：")
    ok = True
    for table in TABLE_ORDER:
        n_src, n_dst = count(src, table), count(dst, table)
        mark = "✓" if n_src == n_dst else "✗ 不一致"
        if n_src != n_dst:
            ok = False
        print(f"  {table:<22} 源 {n_src:>4}  目标 {n_dst:>4}   {mark}")

    print("\n源库没有被修改，回退只需把 .env 里的 DATABASE_URL 删掉。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
