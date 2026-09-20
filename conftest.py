"""pytest 全局配置。

作用：像 main_server.py 那样加载项目根目录的 .env。

为什么需要它：JWT_SECRET / TIMESTAMP_SECRET 现在是"未设置就报错"的必填项
（见 services/auth.py 与 services/chat_common.py 的说明），
而测试进程不会自己读 .env。有了这个文件，本地跑测试能直接复用 .env 里的值；
CI 里则由 workflow 显式注入测试用的值。

⚠️ 一个连带效果，用之前要知道：
    因为这里加载了 .env，**本地的 pytest 会跟着 .env 里的 DATABASE_URL 走**。
      * .env 配了 MySQL  → 测试连的是 MySQL（好处：换库后测试直接帮你验证一遍）
      * .env 没有这行    → 走默认的 SQLite
      * CI 里没有 .env   → 永远走 SQLite，不依赖外部服务
    所以本地如果 MySQL 没起，pytest 会在 import models.orm 时连接失败。
    想强制让测试跑在 SQLite 上（比如排查"到底是不是库的问题"），临时这样做：
        $env:DATABASE_URL="sqlite:///./assert/sever.db"; python -m pytest test -q
"""

from dotenv import load_dotenv

load_dotenv()
