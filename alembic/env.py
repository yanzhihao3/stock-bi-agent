"""Alembic 运行时配置

`alembic init` 生成的是通用模板，这里改了三处（都必要）：

1. target_metadata 指向项目自己的 Base.metadata
   —— 原模板是 None，Alembic 不知道"模型应该长什么样"，autogenerate
      对比不出任何差异（连命令都跑不起来）。

2. 连接库改成复用项目自己的 engine（models.orm.engine）
   —— 原模板从 alembic.ini 的 sqlalchemy.url 读，而 alembic.ini 是**普通文件、
      会提交进 git**：把连接串填进去 = 把数据库密码写进仓库，删文件也留在历史里。
      而且那会变成"第二份配置"（.env 一份、ini 一份），改一处忘一处 →
      迁移连错库。复用 engine 之后目标库完全由 .env 决定，同一套迁移能跑
      SQLite 也能跑 MySQL，不用改迁移文件。

3. 打开 render_as_batch 和 compare_type
   —— SQLite 的 ALTER 能力很弱（不能改列、不能加约束），batch 模式用
      "建新表 → 拷数据 → 换名"来模拟；在 MySQL 上它没有副作用。
      compare_type 让"列类型改了"也能被 autogenerate 检测到（默认不检测）。

⚠️ 必须在 import models.orm **之前** load_dotenv()：orm.py 自己不加载 .env
   （项目约定由入口负责）。忘了这里会静默连到 SQLite，然后对着 MySQL 库
   生成一堆错误的差异。
⚠️ 在**项目根目录**运行 alembic —— prepend_sys_path = . 和 .env 的查找都依赖它。
"""
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv

load_dotenv()   # ← 必须在下一行之前

from models.orm import Base, engine as project_engine   # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _common_kwargs() -> dict:
    return {
        "target_metadata": target_metadata,
        # SQLite 改列必须靠 batch 模式；MySQL 上无副作用
        "render_as_batch": True,
        # 列类型变了也要能检测出来（默认不检测）
        "compare_type": True,
    }


def run_migrations_offline() -> None:
    """离线模式：只输出 SQL、不连库（alembic upgrade head --sql）。"""
    context.configure(
        # ⚠️ 不能写 str(project_engine.url) —— URL.__str__ 会把密码打码成 ***
        url=project_engine.url.render_as_string(hide_password=False),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_common_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with project_engine.connect() as connection:
        context.configure(connection=connection, **_common_kwargs())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()