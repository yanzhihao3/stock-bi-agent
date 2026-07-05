import asyncio
import os
import requests  # type: ignore
from dotenv import load_dotenv
from fastmcp import FastMCP, Client

load_dotenv()

from api.autostock import app
from api.news import mcp as news_mcp
from api.saying import mcp as saying_mcp
from api.tool import mcp as tool_mcp

# 将 FastAPI 应用转换为 MCP 服务器 原来 @app.get() 的端点会变成 AI 可调用的工具
mcp = FastMCP.from_fastapi(app=app)



# prefix="" 表示不加前缀（保持原工具名）
# 如果设置 prefix="news_"，原来的 get_today_daily_news 会变成 news_get_today_daily_news
# 第1步：从 FastAPI 应用创建一个 MCP 服务器（包含自选股/股票相关工具）
# 第2步：往这个 mcp 里继续添加其他 MCP 服务器的工具
# 所以 mcp 不是一个"转换结果"，而是一个容器：
# import_server() 的作用是把其他 MCP 服务器的工具"拷贝"到当前 MCP 服务器里，最终 main_mcp.py 对外只暴露一个统一的 mcp 对象，AI 调用时不需要知道工具原来在哪个文件里。
async def setup():
    await mcp.import_server(news_mcp, prefix="")
    await mcp.import_server(saying_mcp, prefix="")
    await mcp.import_server(tool_mcp, prefix="")

#  测试工具列表
async def _debug_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print("Available tools:", [t.name for t in tools])
        print("Available tools:", [t for t in tools])

if __name__ == "__main__":
    # 作用：Python 用来运行异步函数的工具。因为 setup() 和 test_filtering() 是 async def 定义的，所以需要用 asyncio.run() 来执行。
    asyncio.run(setup())
    asyncio.run(_debug_tools())
    mcp.run(transport="sse", port=8900)
