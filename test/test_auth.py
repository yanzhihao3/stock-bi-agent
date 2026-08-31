"""JWT 认证与密码哈希单元测试（不依赖外部 API / Redis）"""

import hashlib

import pytest
from fastapi import HTTPException

from services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHash:
    def test_hash_verify_roundtrip(self):
        stored = hash_password("123456")
        assert stored.startswith("pbkdf2_sha256$")
        assert verify_password("123456", stored)
        assert not verify_password("wrong-password", stored)

    def test_hash_is_salted(self):
        """相同密码两次哈希结果不同（随机盐）"""
        assert hash_password("123456") != hash_password("123456")

    def test_legacy_sha256_compat(self):
        """旧版无盐 SHA256 密码仍可校验，保证存量用户无需重置密码"""
        legacy = hashlib.sha256("123456".encode()).hexdigest()
        assert verify_password("123456", legacy)


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token("alice", "管理员")
        payload = decode_access_token(token)
        assert payload["sub"] == "alice"
        assert payload["role"] == "管理员"
        assert payload["exp"] > payload["iat"]

    def test_tampered_token_rejected(self):
        token = create_access_token("alice", "普通用户")
        tampered = token[:-2] + ("ab" if token[-2:] != "ab" else "cd")
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(tampered)
        assert exc_info.value.status_code == 401

    def test_expired_token_rejected(self, monkeypatch):
        monkeypatch.setattr("services.auth.JWT_EXPIRE_MINUTES", -1)
        token = create_access_token("alice", "普通用户")
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401
