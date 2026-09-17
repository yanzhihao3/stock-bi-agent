"""MCP SSE → LangChain 工具适配器

将 FastMCP 服务（main_mcp.py, 端口 8900）的 MCP 工具包装为 LangChain BaseTool。
"""

import asyncio
import json
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

# _server_url	str	MCP服务地址，默认本地8900端口的SSE端点
# _sse_ctx	上下文管理器	SSE连接上下文，用于资源清理
# _session	ClientSession	MCP客户端会话，负责发送请求
# _read	流	SSE读取流，接收服务器消息
# _write	流	SSE写入流，发送客户端请求
# _connected	bool	连接状态标志
# _tools_cache	list	缓存工具列表，避免重复获取
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
        # 建连锁：防止并发请求各建一条连接、互相覆盖 self._sse_ctx。
        # 连接改成进程级共享之后就多了这个风险 ——
        # "检查 _connected → 建连接"这个序列本身没有原子性。
        self._connect_lock = asyncio.Lock()

    async def connect(self):
        """建立 MCP SSE 连接（并发安全）。

        为什么需要锁：两个请求同时进来时，都会看到 self._connected 是 False，
        于是各自建一条 SSE 连接并写入 self._sse_ctx —— 后写的覆盖先写的，
        被覆盖的那条随即变成垃圾，GC 在别的 asyncio 任务里清理它时会报
        "Attempted to exit cancel scope in a different task"，
        并且把当时正在使用的连接一起取消掉。
        实测：共享连接下并发 2 路必现（ClosedResourceError / CancelledError）。
        """
        if self._connected:
            return
        async with self._connect_lock:
            # 双重检查：等锁的这段时间里，别的请求可能已经把连接建好了
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
        # 就是 connect() 的逆操作。注意顺序：先挂会话，再挂线路——就像先说完"再见"再挂电话
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
        self._tools_cache = None # 清空缓存

# 第一次调用 → 未连接 → 连接 → 获取工具 → 缓存 → 返回
# 第二次调用 → 已连接 → 缓存命中 → 直接返回（无网络请求） 问 MCP "你有什么工具？"
    async def list_tools(self) -> list:
        """获取 MCP 工具列表"""
        if not self._connected:
            await self.connect()
        if self._tools_cache is None:
            result = await self._session.list_tools()
            self._tools_cache = result.tools  # 记下来，下次不用再问
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
    #  你跟 MCP 说："帮我调用 get_stock_price，参数是 {code: "000001"}"
    #   ▎ MCP 执行完，返回一段文本结果
    #   MCP 返回的 result.content 是一个列表（可能有多个片段），这里把它们拼成一段完整的文字。

    async def get_langchain_tools(self, allowed_names: Optional[list[str]] = None) -> list[StructuredTool]:
        """获取 LangChain 兼容的工具列表，可按名称过滤"""
        mcp_tools = await self.list_tools() # 先拿到 MCP 工具列表
        lc_tools = []

        for tool in mcp_tools:
            if allowed_names and tool.name not in allowed_names:
                continue # 只保留允许的工具

            schema = tool.inputSchema or {} # 获取参数定义
            properties = schema.get("properties", {})

            # 创建 LangChain StructuredTool # ⭐ 关键：包装成 LangChain 的 StructuredTool
            lc_tool = StructuredTool.from_function(
                name=tool.name,
                description=tool.description or tool.name,
                # 用 coroutine 包装器捕获 session
                coroutine=self._make_async_func(tool.name),
                args_schema=self._build_args_schema(tool.name, properties),  # 参数类型
            )
            lc_tools.append(lc_tool)

        return lc_tools
#   到底在干什么？
    #
    #   MCP 那边的一个工具长这样：
    #
    #   {
    #       name: "get_stock_price",
    #       description: "获取股票实时价格",
    #       inputSchema: {
    #           properties: {
    #               code: { type: "string", description: "股票代码" },
    #               market: { type: "string", description: "市场" }
    #           }
    #       }
    #   }
    #
    #   这个函数把它翻译成 LangChain 认识的格式：
    #
    #   StructuredTool(
    #       name="get_stock_price",
    #       description="获取股票实时价格",
    #       coroutine=async def get_stock_price(code, market): ...  # 实际干活
    #       args_schema=get_stock_price_args(code: str, market: str)  # 参数类型
    #   )

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


# ---------------------------------------------------------------
# 进程级共享的 MCP 连接
#
# 注意：这一段必须放在文件的**最末尾**（类定义全部结束之后）。
# 上次插在类体中间，导致类后面那几个方法被当成新函数的函数体，
# 结果 MCPClientManager 直接丢了 get_langchain_tools 等方法 ——
# 而且 py_compile 检查不出来，因为缩进在语法上是合法的。
# ---------------------------------------------------------------
_default_manager: Optional[MCPClientManager] = None


def get_mcp_manager(server_url: str = "http://localhost:8900/sse") -> MCPClientManager:
    """返回进程内共享的 MCP 连接管理器（懒创建）。

    为什么要有这个函数 —— 原来每次对话都新建一个 manager、用完 disconnect()，
    问题不在于多拉一次工具列表这点开销，而在于：

      connect() / disconnect() 是被**手工**调用的 async context manager。
      断开之后，下一个请求会新建一个 sse_client 上下文，旧的那个随即变成垃圾；
      当 GC 在**另一个 asyncio 任务**里关闭它时，就会报
      "Attempted to exit cancel scope in a different task than it was entered in"，
      并且把当时正在进行的连接一起取消掉 —— langchain 引擎跑评测就是这样崩的。

    改成进程级共享后：
      1. 连接不再每轮重建，省掉重复的 SSE 握手与 list_tools；
      2. 那个上下文对象始终被这个单例引用着，永远不会被 GC —— 崩溃的机理从根上消失。

    注意：共享之后多个请求共用一个 MCP 会话，并发安全需要实测
    （ClientSession 用请求 ID 匹配响应，理论上支持并发）。
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = MCPClientManager(server_url)
    return _default_manager
