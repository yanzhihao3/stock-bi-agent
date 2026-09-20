"""pytest 全局配置。

作用：像 main_server.py 那样加载项目根目录的 .env。

为什么需要它：JWT_SECRET / TIMESTAMP_SECRET 现在是"未设置就报错"的必填项
（见 services/auth.py 与 services/chat_common.py 的说明），
而测试进程不会自己读 .env。有了这个文件，本地跑测试能直接复用 .env 里的值；
CI 里则由 workflow 显式注入测试用的值。

⚠️ 数据库：**测试固定跑 SQLite**，即使 .env 里配了 MySQL。

    为什么强制：测试应该是 hermetic 的 —— 不依赖外部服务。不然 MySQL 没起
    pytest 就红一片，而那跟被测代码对不对没关系。而且 CI 里没有 .env、
    本来就走 SQLite，本地强制一下能让两边行为一致。

    代价：换库之后单测不会帮你验证 MySQL 那条路。那个交给
    `python scripts/db_status.py`（看连的是哪个库）和把服务跑起来实测。

    做法是加载完 .env 再把 DB_PASSWORD 摘掉，于是 build_database_url() 落到
    默认的 SQLite（见 models/db_url.py 的优先级）。
"""

import os

from dotenv import load_dotenv

load_dotenv()

# 摘掉 DB_PASSWORD → 测试一律走 SQLite（理由见上面的 docstring）
os.environ.pop("DB_PASSWORD", None)
