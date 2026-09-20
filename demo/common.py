"""Streamlit 前端公共工具：统一后端地址与 JWT 请求头

⚠️ **所有前端页面都必须从这里取地址，不要再自己写 `http://127.0.0.1:8000`。**

为什么专门写这条：历史上 8 个股票页面各自写了一份 `BASE_URL`，加上其他页面一共
十来处。后果是——
  * 改端口/改域名/换机器 IP 都得改代码，而且很容易漏掉一两处
  * docker-compose 之所以必须把三个进程塞进**同一个容器**，就是因为这些地址
    写死成了 localhost，而容器之间 localhost 并不是同一个

现在改成环境变量可覆盖（docker-compose 或 .env 里注入 `API_BASE_URL` 即可），
拆容器 / 换域名 / 换端口都只是改配置，不用动代码。
"""

import os

import streamlit as st

# 后端地址。默认本机 8000，可用环境变量覆盖
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
# 底层股票接口挂在 /stock 前缀下（main_server.py 里 app.mount("/stock", stock_app)）
STOCK_API_BASE_URL = f"{API_BASE_URL}/stock"
# MCP 服务地址。Streamlit 的 MCP 列表/调试页要直接连它
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8900/sse")


def auth_headers() -> dict:
    """返回携带 JWT 的请求头；未登录时返回空字典（后端会返回 401）"""
    token = st.session_state.get("token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}
