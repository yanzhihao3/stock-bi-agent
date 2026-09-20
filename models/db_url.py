"""数据库连接串的解析 —— 独立模块，**没有副作用**

为什么不直接写在 models/orm.py 里：orm.py 在 import 时会 create_all 建表，
而 scripts/migrate_sqlite_to_mysql.py 这类工具**不该**有那个副作用
（迁移工具连目标库只是为了写数据，不该顺手把表建了）。把「解析配置」和
「定义模型 + 建表」分开，前者无副作用，两边都能安全 import。

⚠️ 本模块**不加载 .env**（项目约定：由入口负责 load_dotenv）。独立脚本记得先加载。
"""

import os
from typing import Optional

from sqlalchemy.engine import URL, make_url

DEFAULT_SQLITE_URL = "sqlite:///./assert/sever.db"


def _as_int(value: Optional[str]) -> Optional[int]:
    if value is None or not str(value).strip():
        return None
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(f"DB_PORT 必须是数字，收到 {value!r}") from None


def build_database_url() -> URL:
    """决定连哪个库。**只有两种状态，没有第三种**：

      * 配了 `DB_PASSWORD`（说明你要用 MySQL）→ 用 DB_* 分量拼出连接串
      * 没配 → SQLite 默认值，保证 clone 下来零配置能跑（CI 和 Docker 靠它）

    **为什么是「分量」而不是「一整条连接串」**（这是本模块存在的理由）：

    连接串是 URI，里面的 `@ : / # ?` 都是**结构性字符**，不是普通分隔符。
    密码里出现 `@` 时，解析器会把它当成「账号密码」和「主机」的分隔符 ——
    实测密码 `p@ss123` 会让 host 变成 `ss123@127.0.0.1`，而报错是
    「连不上主机」，一个字都不提密码，排查时会被带到完全错误的方向。

    分量写法把各个部分分开传，转义交给 `URL.create()` —— 使用者不用关心
    密码里有什么字符。反过来要求"手写一整条 URL"的话，就得自己记得编码，
    而"要记得"本身就是隐患。

    （一开始这两种写法我都支持了。结果是使用者得理解两个概念、还要记住
    优先级 —— 为一个不存在的场景付出的复杂度。所以删掉了。）
    """
    # 用 `is not None` 而不是真值判断：允许显式的空密码
    if os.environ.get("DB_PASSWORD") is not None:
        return URL.create(
            drivername=(os.environ.get("DB_DRIVER") or "mysql+pymysql").strip(),
            username=(os.environ.get("DB_USER") or "").strip() or None,
            password=os.environ.get("DB_PASSWORD") or None,
            host=(os.environ.get("DB_HOST") or "").strip() or None,
            port=_as_int(os.environ.get("DB_PORT")),
            database=(os.environ.get("DB_NAME") or "").strip() or None,
            query={"charset": (os.environ.get("DB_CHARSET") or "utf8mb4").strip()},
        )

    return make_url(DEFAULT_SQLITE_URL)


def describe(url: URL) -> str:
    """给日志/终端用的一行描述。

    打码**不用自己写正则** —— SQLAlchemy 的 `render_as_string(hide_password=True)`
    就是干这个的，而且它认得自己的转义规则，比手写的正则可靠。
    """
    return url.render_as_string(hide_password=True)
