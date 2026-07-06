"""MCP SSE → LangChain 工具适配器

将 FastMCP 服务（main_mcp.py, 端口 8900）的 MCP 工具包装为 LangChain BaseTool。
"""

import asyncio
import json
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession


class MCPClientManager:
    """管理 MCP SSE 连接，提供 LangChain 兼容的工具"""

    def __init__(self, server_url: str = "http://localhost:8900/sse"):
        self._server_url = server_url
        self._sse_ctx: Optional[Any] = None
        self._session: Optional[ClientSession] = None
        self._read: Optional[Any] = None
        self._write: Optional[Any] = None
        self._connected = False
        self._tools_cache: Optional[list] = None

    async def connect(self):
        """建立 MCP SSE 连接"""
        if self._connected:
            return
        self._sse_ctx = sse_client(self._server_url)
        self._read, self._write = await self._sse_ctx.__aenter__()
        self._session = ClientSession(self._read, self._write)
        await self._session.__aenter__()
        await self._session.initialize()
        self._connected = True

    async def disconnect(self):
        """关闭 MCP 连接"""
        self._connected = False
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except (Exception, asyncio.CancelledError):
                pass
            self._session = None
        if self._sse_ctx:
            try:
                await self._sse_ctx.__aexit__(None, None, None)
            except (Exception, asyncio.CancelledError):
                pass
            self._sse_ctx = None
        self._tools_cache = None

    async def list_tools(self) -> list:
        """获取 MCP 工具列表"""
        if not self._connected:
            await self.connect()
        if self._tools_cache is None:
            result = await self._session.list_tools()
            self._tools_cache = result.tools
        return self._tools_cache

    async def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具，返回文本结果"""
        if not self._connected:
            await self.connect()
        result = await self._session.call_tool(name, arguments)
        # result.content 是 TextContent 列表，拼接为字符串
        texts = []
        for item in result.content:
            if hasattr(item, "text") and item.text:
                texts.append(item.text)
        return "\n".join(texts)

    async def get_langchain_tools(self, allowed_names: Optional[list[str]] = None) -> list[StructuredTool]:
        """获取 LangChain 兼容的工具列表，可按名称过滤"""
        mcp_tools = await self.list_tools()
        lc_tools = []

        for tool in mcp_tools:
            if allowed_names and tool.name not in allowed_names:
                continue

            schema = tool.inputSchema or {}
            properties = schema.get("properties", {})

            # 创建 LangChain StructuredTool
            lc_tool = StructuredTool.from_function(
                name=tool.name,
                description=tool.description or tool.name,
                # 用 coroutine 包装器捕获 session
                coroutine=self._make_async_func(tool.name),
                args_schema=self._build_args_schema(tool.name, properties),
            )
            lc_tools.append(lc_tool)

        return lc_tools

    def _make_async_func(self, tool_name: str):
        """为指定工具创建异步调用函数"""
        async def _call(**kwargs) -> str:
            return await self.call_tool(tool_name, kwargs)
        # 直接返回异步函数，LangChain 会识别 coroutine
        _call.__name__ = tool_name
        return _call

    def _build_args_schema(self, tool_name: str, properties: dict):
        """从 JSON Schema properties 构建 Pydantic 参数模型"""
        from pydantic import create_model, Field

        fields = {}
        for prop_name, prop_info in properties.items():
            prop_type = self._json_type_to_python(prop_info)
            prop_desc = prop_info.get("description", "")
            fields[prop_name] = (prop_type, Field(description=prop_desc))

        if not fields:
            return None

        return create_model(f"{tool_name}_args", **fields)

    @staticmethod
    def _json_type_to_python(prop_info: dict):
        """将 JSON Schema 类型映射为 Python 类型"""
        json_type = prop_info.get("type", "string")
        mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        return mapping.get(json_type, str)


