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
    user_name: Mapped[str] = mapped_column(String)
    user_role: Mapped[str] = mapped_column(String)
    password: Mapped[str] = mapped_column(String)
    register_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[bool] = mapped_column(Boolean)

# DataTable - 数据文件表 用途：存储用户上传的文件信息
class DataTable(Base):
    __tablename__ = 'data'
    id = Column(Integer, primary_key=True)
    path = Column(String) # 文件路径
    data_type = Column(String) # 数据类型
    create_user_id = Column(Integer, ForeignKey('user.id')) # 上传者
    create_time = Column(DateTime)
    alter_time = Column(DateTime)

# 自选股表
class UserFavoriteStockTable(Base):
    __tablename__ = 'user_favorite_stock'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[int] = Column(Integer, ForeignKey('user.id'))
    create_time: Mapped[datetime] = Column(DateTime, default=datetime.utcnow)

#  对话会话表
# nullable=False 是数据库字段的约束条件，意思是这个字段不能为空
class ChatSessionTable(Base):
    """表1，存储一次对话列表的基础信息，聊天会话模型：存储用户会话的元数据。"""
    __tablename__ = 'chat_session'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    session_id = Column(String)
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

DATABASE_URL = "sqlite:///./assert/sever.db" # 数据库连接地址
# 建立与数据库的连接，是 SQLAlchemy 的核心入口
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} # SQLite多线程访问需要
)
# connect_args	{"check_same_thread": False}	SQLite 专用，允许多个线程访问同一个数据库
# 为什么需要 check_same_thread: False？
# FastAPI 是多线程环境
# SQLite 默认只允许创建连接的线程访问
# 设置 False 后，其他线程也能访问

Base.metadata.create_all(bind=engine) # 创建所有表
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# autocommit	False	不自动提交，需要手动 commit()
# autoflush	False	不自动刷新，需要手动 flush()
# bind	engine	绑定到哪个数据库
