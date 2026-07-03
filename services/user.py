import hashlib
import traceback
from typing import Optional, List
from models.orm import UserTable, SessionLocal
from models.data_models import User

# 这段代码是完整的用户管理模块，实现了用户的注册、登录、查询、删除、修改等核心功能。

def password_hash(password: str) -> str:
    """对密码进行哈希处理。"""
    # 作用：将明文密码转换为不可逆的哈希值
    return hashlib.sha256(password.encode()).hexdigest()
    # SHA256输出：64个字符（不管输入多长）

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

def user_register(user_name: str, password: str, user_role: str) -> bool:
    with SessionLocal() as session:
        user = session.query(UserTable).filter(UserTable.user_name == user_name).first()
        if user is not None:
            return False
        # 创建新用户（密码加密）
        password = password_hash(password)
        user = UserTable(user_name=user_name, password=password, user_role=user_role, status=True) # status=True 账户状态：启用
        session.add(user)
        session.commit()
        return True

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

def user_login(username: str, password: str) -> bool:
    with SessionLocal() as session:
        user = session.query(UserTable).filter(UserTable.user_name == username).first()
        if user is None:
            return False
        # 验证密码（加密后对比）
        password = password_hash(password)
        if user.password != password:
            return False

        return True


def user_delete(user_name: str) -> bool:
    try:
        with SessionLocal() as session:
            user = session.query(UserTable).filter(UserTable.user_name == user_name).first()
            if user is None:
                return False

            session.delete(user)
            session.commit()
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

        user.password = password_hash(password)  # type: ignore
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

