#!/usr/bin/env python
"""看一眼数据库现在的状态：用哪个库、表建了没、各表多少行

用法
    python scripts/db_status.py

为什么需要它（而不是直接 import models.orm 看）：
    models/orm.py 自己不加载 .env —— 项目约定由入口负责 load_dotenv()。
    所以直接 import 它的话，`.env` 里的 DB_* 读不到，会**静默走回 SQLite**，
    你会以为在查 MySQL，其实查的是 assert/sever.db。
    这个脚本先 load_dotenv 再 import，并把**最终选中的库**明确打出来。

它**只读**：不建表、不改数据，只做 SHOW / SELECT COUNT / 读 alembic_version。
    （表结构归 Alembic 管 —— models/orm.py 里的 create_all 已经删掉了。
      缺表的话跑 `python -m alembic upgrade head`，不是跑这个脚本。）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 业务库的 6 张表（顺序按外键依赖排，方便肉眼看）
TABLES = ("user", "chat_session", "chat_message", "user_memory",
          "user_favorite_stock", "data")


def mask(url: str) -> str:
    """把连接串里的密码换成 ***。"""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    # 必须在 load_dotenv 之后 import —— 这里就是那个坑
    import models.orm as orm

    from sqlalchemy import inspect, text

    url = str(orm.engine.url)
    dialect = orm.engine.dialect.name
    print(f"连接串      {mask(url)}")
    print(f"数据库类型  {dialect}"
          + ("   ← 默认值，.env 里没配 DB_*" if dialect == "sqlite" else ""))

    if dialect != "sqlite":
        with orm.engine.connect() as conn:
            print(f"MySQL 版本  {conn.execute(text('SELECT VERSION()')).scalar()}")
            print(f"当前库      {conn.execute(text('SELECT DATABASE()')).scalar()}")
            charset = conn.execute(text("SELECT @@character_set_database")).scalar()
            print(f"库字符集    {charset}"
                  + ("" if charset == "utf8mb4" else "   ⚠️ 不是 utf8mb4，中文会有问题"))

    # 只读结果，不建表（表结构归 Alembic 管）
    present = set(inspect(orm.engine).get_table_names())
    print()
    print(f"{'表':<22}{'存在':>6}{'行数':>8}")
    print("-" * 36)
    for table in TABLES:
        if table in present:
            with orm.engine.connect() as conn:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"{table:<22}{'✓':>6}{n:>8}")
        else:
            print(f"{table:<22}{'✗':>6}{'—':>8}")

    missing = [t for t in TABLES if t not in present]
    print()

    # 表结构的版本号（Alembic 的 alembic_version 表）。
    # 它决定了 `alembic upgrade head` 会不会重复建表 —— 所以和"表齐不齐"一样重要。
    if "alembic_version" in present:
        with orm.engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        print(f"表结构版本  {[r[0] for r in rows] or '（空 → 还没 stamp/upgrade 过）'}")
    else:
        print("表结构版本  （没有 alembic_version 表 → 这个库还没接入 Alembic）")

    if missing:
        print(f"缺表：{missing}")
        print("→ 跑 `python -m alembic upgrade head` 建表"
              "（models/orm.py 里已经没有 create_all 了，表结构归 Alembic 管）")
    else:
        print("6 张表齐全。")

    source = ROOT / "assert" / "sever.db"
    if source.exists():
        print()
        print(f"参考：源库 {source.name} 里的行数")
        import sqlite3
        conn = sqlite3.connect(str(source))
        for table in TABLES:
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"  {table:<22}{n:>8}")
            except sqlite3.Error:
                print(f"  {table:<22}{'—':>8}")
        conn.close()


if __name__ == "__main__":
    main()
