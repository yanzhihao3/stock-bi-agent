"""跨进程的地址配置

为什么单独抽一个模块：这些值**两个进程都要用** —— 后端（8000）里的
services/chat.py 要连 MCP，services/mcp_adapter.py 也要连 MCP。散着写的话
改一处漏一处，而且改部署拓扑时根本不知道该动哪几个文件。

现状与将来：
    现在是"三个进程同一个容器"，所以默认值是 localhost。
    想拆成多个容器或跨机器部署，只需在 .env / docker-compose 里注入
        MCP_SERVER_URL=http://mcp:8900/sse
    不用改任何代码。

⚠️ 前端那份同样的常量在 demo/common.py（Streamlit 是另一个进程，
   而且它只认 http:// 形式）。两边都要改的话记得一起改。
"""

import os

# MCP 服务地址（FastMCP 的 SSE 端点）。main_mcp.py 默认监听 8900。
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8900/sse")
