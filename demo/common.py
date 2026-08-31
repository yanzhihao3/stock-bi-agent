"""Streamlit 前端公共工具：统一后端地址与 JWT 请求头"""

import streamlit as st

API_BASE_URL = "http://127.0.0.1:8000"


def auth_headers() -> dict:
    """返回携带 JWT 的请求头；未登录时返回空字典（后端会返回 401）"""
    token = st.session_state.get("token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}
