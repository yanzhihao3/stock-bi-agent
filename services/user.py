import logging
import traceback
from typing import Optional, List
from models.orm import (
    UserTable,
    SessionLocal,
    ChatSessionTable,
    ChatMessageTable,
    UserFavoriteStockTable,
    UserMemoryTable,
)
from models.data_models import User
from services.auth import hash_password, verify_password
from services.chat_common import clear_agent_session_memory

logger = logging.getLogger(__name__)


def check_user_exists(username: str) -> bool:
    """检查用户是否存在。"""
    try:
        with SessionLocal() as session:
            user = session.query(UserTable).filter(UserTable.user_name == username).first()
            if user is None:
                return False

            return True
    except Exception as e:
        traceback.print_exc()
        return False

def user_register(user_name: str, password: str) -> Optional[User]:
    """注册新用户，默认角色为普通用户；第一个注册的用户自动成为管理员（便于初始化）。
    成功返回用户信息（不含密码），用户名已存在返回 None。"""
    with SessionLocal() as session:
        if session.query(UserTable).filter(UserTable.user_name == user_name).first():
            return None
        is_first_user = session.query(UserTable).first() is None
        role = "管理员" if is_first_user else "普通用户"
        user = UserTable(
            user_name=user_name,
            password=hash_password(password),
            user_role=role,
            status=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return User(
            user_id=user.id,
            user_name=user.user_name,
            user_role=user.user_role,
            register_time=user.register_time,
            status=user.status,
        )

# 获取用户信息
def get_user_info(user_name: str) -> Optional[User]:
    try:
        with SessionLocal() as session:
            user_db_record: UserTable|None = session.query(UserTable).filter(UserTable.user_name == user_name).first()
            if user_db_record:
                return User(
                    user_id=user_db_record.id,
                    user_name=user_db_record.user_name,
                    user_role=user_db_record.user_role,
                    register_time=user_db_record.register_time,
                    status=user_db_record.status
                )
            else:
                return None
    except Exception as e:
        traceback.print_exc()
        return None

# 分页查询用户列表
def list_users(page_index:int=1, page_size=200) -> List[User]:
    try:
        with SessionLocal() as session:
            # 分页查询：跳过 (page-1)*size 条，取 size 条
            # page_index - 页码（第几页） page_size - 每页显示多少条   offset() - 跳过多少条  limit() - 取多少条  all() - 执行查询
            user_db_records = session.query(UserTable).offset((page_index-1)*page_size).limit(page_size).all()
            return [
                User(
                user_id=user_db_record.id,
                user_name=user_db_record.user_name,
                user_role=user_db_record.user_role,
                register_time=user_db_record.register_time,
                status=user_db_record.status) for user_db_record in user_db_records
            ]
    except Exception as e:
        traceback.print_exc()
        return []

def authenticate(user_name: str, password: str) -> Optional[User]:
    """校验用户名与密码，成功返回用户信息（不含密码），失败返回 None"""
    with SessionLocal() as session:
        user = session.query(UserTable).filter(UserTable.user_name == user_name).first()
    if user is None or not verify_password(password, user.password):
        return None
    return User(
        user_id=user.id,
        user_name=user.user_name,
        user_role=user.user_role,
        register_time=user.register_time,
        status=user.status,
    )


def check_password(user_name: str, password: str) -> bool:
    """仅校验密码是否正确（用于修改密码前验证原密码）"""
    return authenticate(user_name, password) is not None


def user_delete(user_name: str) -> bool:
    try:
        session_ids: List[str] = []
        with SessionLocal() as session:
            user = session.query(UserTable).filter(UserTable.user_name == user_name).first()
            if user is None:
                return False

            # 先收集该用户的会话（用于后面清理 AI 记忆库）
            chat_sessions = session.query(ChatSessionTable).filter(
                ChatSessionTable.user_id == user.id
            ).all()
            session_ids = [s.session_id for s in chat_sessions]
            chat_ids = [s.id for s in chat_sessions]

            # 级联删除：消息 → 会话 → 自选股 → 长期记忆 → 用户本身
            if chat_ids:
                session.query(ChatMessageTable).filter(
                    ChatMessageTable.chat_id.in_(chat_ids)
                ).delete(synchronize_session=False)
            session.query(ChatSessionTable).filter(
                ChatSessionTable.user_id == user.id
            ).delete(synchronize_session=False)
            session.query(UserFavoriteStockTable).filter(
                UserFavoriteStockTable.user_id == user.id
            ).delete(synchronize_session=False)
            session.query(UserMemoryTable).filter(
                UserMemoryTable.user_id == user.id
            ).delete(synchronize_session=False)
            session.delete(user)
            session.commit()

        # 清理该用户所有会话在 AI 记忆库（conversations.db）里的记录，避免孤儿数据
        for sid in session_ids:
            clear_agent_session_memory(sid)
        return True
    except Exception as e:
        traceback.print_exc()
        return False

#  重置密码
def user_reset_password(user_name: str, password: str) -> bool:
    with SessionLocal() as session:
        user = session.query(UserTable).filter(UserTable.user_name == user_name).first()
        if user is None:
            return False

        user.password = hash_password(password)
        session.commit()
        return True

# 修改用户状态
def alter_user_status(user_name: str, status: bool) -> bool:
    with SessionLocal() as session:
        user = session.query(UserTable).filter(UserTable.user_name == user_name).first()
        if user is None:
            return False
        user.status = status  # # True=启用, False=禁用# type: ignore
        session.commit()
        return True

# 修改用户角色
def alter_user_role(user_name: str, user_role: str) -> bool:
    with SessionLocal() as session:
        user = session.query(UserTable).filter(UserTable.user_name == user_name).first()
        if user is None:
            return False

        user.user_role = user_role  # type: ignore
        session.commit()
        return True
