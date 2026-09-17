"""pytest 全局配置。

作用：像 main_server.py 那样加载项目根目录的 .env。

为什么需要它：JWT_SECRET / TIMESTAMP_SECRET 现在是"未设置就报错"的必填项
（见 services/auth.py 与 services/chat_common.py 的说明），
而测试进程不会自己读 .env。有了这个文件，本地跑测试能直接复用 .env 里的值；
CI 里则由 workflow 显式注入测试用的值。
"""

from dotenv import load_dotenv

load_dotenv()
