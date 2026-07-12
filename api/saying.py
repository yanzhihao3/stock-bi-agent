import os
import requests
TOKEN = os.environ.get("WHYTA_TOKEN", "")

# 励志名言 MCP 服务器

from fastmcp import FastMCP
mcp = FastMCP(
    name="Saying-MCP-Server",
    instructions="""This server contains some api of saying.""",
)

@mcp.tool(tags={"名言鸡汤"})
def get_today_familous_saying():
    """Retrieves a random famous saying or 'hitokoto' quote using the external API."""
    try:
        # 返回字段: ["hitokoto"] - 一个随机名言（类似“一言”服务） 经典的“Hitokoto·一言”风格，每次返回一句随机的话
        return requests.get(f"https://whyta.cn/api/yiyan?key={TOKEN}", timeout=5).json()["hitokoto"]
    except:
        return []

@mcp.tool(tags={"名言鸡汤"})
def get_today_motivation_saying():
    """Retrieves a motivation saying or inspirational quote from the API."""
    try:
        # 返回字段: ["result"] - 励志名言（可能包含标题、内容、作者等） 特点: 返回完整的励志句子对象
        return requests.get(f"https://whyta.cn/api/tx/lzmy?key={TOKEN}", timeout=5).json()["result"]
    except:
        return []

@mcp.tool(tags={"名言鸡汤"})
def get_today_working_saying():
    """Retrieves a quote related to work or chicken soup for the soul (心灵鸡汤) content."""
    try:
        # 返回字段: ["result"]["content"] - 只提取名言中的内容部分 特点: 专门用于职场励志或心灵鸡汤场景
        return requests.get(f"https://whyta.cn/api/tx/lzmy?key={TOKEN}", timeout=5).json()["result"]["content"]
    except:
        return []