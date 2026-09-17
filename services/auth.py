"""JWT 认证与密码哈希工具

- 登录/注册成功后签发 JWT（HS256），后续请求通过 `Authorization: Bearer <token>` 携带
- 密码使用带盐 PBKDF2-SHA256 存储，兼容旧版无盐 SHA256（旧用户无需重置密码即可登录）
- 提供 FastAPI 依赖：`get_current_user`（登录校验）、`require_admin`（管理员校验）
"""

import hashlib
import hmac # 恒定时间比较（防时序攻击）
import os
import secrets # 生成安全的随机盐
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
# FastAPI 工具，自动从 Header 提取 Authorization: Bearer <token>

from models.orm import SessionLocal, UserTable

# 刻意不给默认值：此前这里有一串公开常量兜底，部署时忘记设置 JWT_SECRET 也能照常启动，
# 而那串字符串写在 GitHub 上人人可见 —— 任何人都能用它签出 role=管理员 的令牌，
# 绕过全部鉴权。宁可启动时明确失败，也不要静默降级到一个人人皆知的密钥。
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "必须设置 JWT_SECRET 环境变量（参考 .env.example）。\n"
        "生成方式：python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "注意：改这个值会让所有已签发的登录令牌立即失效。"
    )
JWT_ALGORITHM = "HS256"
# 默认 24 小时，可通过环境变量调整
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "1440"))

# 密码哈希迭代次数（OWASP 建议 2023 年后 PBKDF2-SHA256 至少 60 万次，
# 这里取一个兼顾性能的默认值，可按需调大） 密码哈希迭代次数（12 万次，让破解变慢
PBKDF2_ITERATIONS = 120_000

_bearer_scheme = HTTPBearer(auto_error=False) # FastAPI 工具，自动解析 Authorization: Bearer xxx


# ---------------- 密码哈希 ----------------


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 加盐哈希，存储格式：pbkdf2_sha256$iterations$salt$digest"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    """校验密码；兼容旧版无盐 SHA256 格式（不含 $ 前缀时走旧逻辑）"""
    if stored_hash.startswith("pbkdf2_sha256$"):
        _, iterations, salt, digest = stored_hash.split("$")
        calc = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(calc, digest)
    legacy = hashlib.sha256(password.encode()).hexdigest()
    return hmac.compare_digest(legacy, stored_hash)


# ---------------- JWT ----------------


def create_access_token(user_name: str, user_role: str) -> str:
    """签发 JWT，包含用户名（sub）与角色（role）"""
    now = int(time.time())
    payload = {
        "sub": user_name,
        "role": user_role,
        "iat": now,
        "exp": now + JWT_EXPIRE_MINUTES * 60,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解码并校验 JWT，失败统一抛 401 HTTPException"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的登录凭证")


# ---------------- FastAPI 依赖 ----------------


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> UserTable:
    """从 Authorization 头解析当前登录用户，返回数据库中的用户记录"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_access_token(credentials.credentials)
    user_name = payload.get("sub")
    if not user_name:
        raise HTTPException(status_code=401, detail="无效的登录凭证")

    with SessionLocal() as session:
        user = session.query(UserTable).filter(
            UserTable.user_name == user_name
        ).first()

    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not user.status:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def require_admin(user: UserTable = Depends(get_current_user)) -> UserTable:
    """管理员权限依赖，非管理员直接 403"""
    if user.user_role != "管理员":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
