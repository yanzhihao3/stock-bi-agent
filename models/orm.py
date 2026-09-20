import os

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column

# 这段代码是数据库ORM模型定义和初始化文件，使用 SQLAlchemy 定义数据库表结构。让我详细解析：
# 一句话总结：定义数据库的表结构，并创建数据库连接，是数据持久化的基础。
# reate_engine	创建数据库连接
# DeclarativeBase	ORM模型基类
# sessionmaker	创建数据库会话工厂
# Mapped, mapped_column	现代SQLAlchemy类型注解

class Base(DeclarativeBase):
    pass

# 用户表
# = mapped_column(String)	列定义	告诉SQLAlchemy这是数据库的列
class UserTable(Base):
    __tablename__ = 'user'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ⚠️ MySQL 的 VARCHAR 必须带长度（SQLite 不要求），所以这些列都得写死长度，
    # 否则 Base.metadata.create_all() 会直接报
    #   CompileError: VARCHAR requires a length on dialect mysql
    user_name: Mapped[str] = mapped_column(String(50))
    user_role: Mapped[str] = mapped_column(String(20))
    password: Mapped[str] = mapped_column(String(255))  # 存的是 bcrypt 哈希，60 字符，留余量
    register_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[bool] = mapped_column(Boolean)

# DataTable - 数据文件表 用途：存储用户上传的文件信息
class DataTable(Base):
    __tablename__ = 'data'
    id = Column(Integer, primary_key=True)
    path = Column(String(500)) # 文件路径
    data_type = Column(String(50)) # 数据类型
    create_user_id = Column(Integer, ForeignKey('user.id')) # 上传者
    create_time = Column(DateTime)
    alter_time = Column(DateTime)

# 自选股表
class UserFavoriteStockTable(Base):
    __tablename__ = 'user_favorite_stock'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[str] = mapped_column(String(20))  # 形如 sh600519
    user_id: Mapped[int] = Column(Integer, ForeignKey('user.id'))
    create_time: Mapped[datetime] = Column(DateTime, default=datetime.utcnow)

#  对话会话表
# nullable=False 是数据库字段的约束条件，意思是这个字段不能为空
class ChatSessionTable(Base):
    """表1，存储一次对话列表的基础信息，聊天会话模型：存储用户会话的元数据。"""
    __tablename__ = 'chat_session'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    session_id = Column(String(32))  # 随机 12 位，留余量
    title = Column(String(100))
    start_time = Column(DateTime, default=datetime.now)
    feedback: Mapped[bool] = mapped_column(Boolean, nullable=True)
    feedback_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)

#  聊天消息表
# index=True 是数据库的索引设置，意思是为这个字段创建索引，可以加快查询速度
class ChatMessageTable(Base):
    """表2，存储一次对话的每一条记录，聊天消息模型：存储会话中的每一条消息。"""
    __tablename__ = 'chat_message'

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey('chat_session.id'), nullable=False)
    role = Column(String(10), nullable=True)
    content = Column(Text, nullable=True)
    generated_sql = Column(Text, nullable=True)
    generated_code = Column(Text, nullable=True)
    create_time = Column(DateTime, default=datetime.now)
    feedback: Mapped[bool] = mapped_column(Boolean, nullable=True)
    feedback_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)

# 用户级长期记忆表
# 作用：跨会话记住用户的偏好/事实（例如"用户关注新能源板块"、"用户喜欢简洁回答"），
#       在每次对话时注入系统提示词，让 AI 记住这个用户。
# 清理规则：删除用户时必须连同此表的记录一起删除，否则会留下孤儿数据。
class UserMemoryTable(Base):
    __tablename__ = 'user_memory'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(50), nullable=False)  # 记忆类别：preference / fact / habit
    content: Mapped[str] = mapped_column(Text, nullable=False)    # 记忆内容
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

# 数据库连接地址。
#
# ⚠️ 本模块**不自己加载 .env**（项目约定：由入口负责 load_dotenv）。所以：
#   - main_server.py / main_mcp.py / eval/run_eval.py 都会先 load_dotenv，正常
#   - 但独立脚本（比如你临时写的 python -c）忘了加载的话，这里会**静默走回
#     SQLite** —— 你以为在建 MySQL 的表，其实建在了 assert/sever.db 上
#   独立使用请先 `from dotenv import load_dotenv; load_dotenv()`，
#   或者直接用 `python scripts/db_status.py`（它会把目标库打出来）。
#
# **默认仍然是 SQLite** —— 换 MySQL 只是往 .env 里加一行 DATABASE_URL：
#   DATABASE_URL=mysql+pymysql://root:<密码>@127.0.0.1:3306/stock_bi?charset=utf8mb4
#
# 为什么默认值留 SQLite：一是让 clone 下来不配任何东西就能跑（CI、Docker、
# 别人试用）；二是换库失败时**回退成本为零** —— 把 .env 那行删掉就回去了，
# 不用改代码、不用回滚数据库。
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./assert/sever.db")
DB_FILE_PATH = "./assert/sever.db"

# 这个目录必须**无条件**创建，不能只在 SQLite 分支里建：
# 换到 MySQL 之后，业务库是远程的了，但 Agents SDK 的记忆库
# （./assert/conversations.db）**仍然是本地 SQLite 文件**，它也需要这个目录。
#
# 另外 SQLite 只创建"文件"、不创建"文件所在的目录"：目录不存在时（全新 clone、
# 干净的 CI 环境、新容器）create_all 会以「unable to open database file」失败，
# 连 import 都过不去。
os.makedirs(os.path.dirname(DB_FILE_PATH), exist_ok=True)

if DATABASE_URL.startswith("sqlite"):
    # SQLite 专用参数：默认只允许创建连接的那个线程访问，而 FastAPI 是多线程的
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # MySQL 的两个连接池参数是刚需，不是可选优化：
    #   pool_pre_ping —— 每次取连接前先 ping 一下，避免拿到已被服务端断掉的连接
    #   pool_recycle  —— MySQL 默认 8 小时回收空闲连接，不设的话会间歇报
    #                    "MySQL server has gone away"，而且很难复现
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=5,
        max_overflow=10,
    )

Base.metadata.create_all(bind=engine) # 创建所有表
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# autocommit	False	不自动提交，需要手动 commit()
# autoflush	False	不自动刷新，需要手动 flush()
# bind	engine	绑定到哪个数据库
