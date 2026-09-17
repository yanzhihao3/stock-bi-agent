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
    """随机返回一句名言/一言（文艺向，来自影视、动漫、文学）。
    什么时候用：用户说"来句名言""说点有文采的话"。"""
    try:
        # 返回字段: ["hitokoto"] - 一个随机名言（类似“一言”服务） 经典的“Hitokoto·一言”风格，每次返回一句随机的话
        return requests.get(f"https://whyta.cn/api/yiyan?key={TOKEN}", timeout=5).json()["hitokoto"]
    except:
        return []

@mcp.tool(tags={"名言鸡汤"})
def get_today_motivation_saying():
    """返回一句励志语录（打气、正能量）。
    什么时候用：用户说"鼓励我一下""说句励志的话""心情不好想听点积极的话"。"""
    try:
        # 返回字段: ["result"] - 励志名言（可能包含标题、内容、作者等） 特点: 返回完整的励志句子对象
        return requests.get(f"https://whyta.cn/api/tx/lzmy?key={TOKEN}", timeout=5).json()["result"]
    except:
        return []

@mcp.tool(tags={"名言鸡汤"})
def get_today_working_saying():
    """返回一句职场/打工主题的语录（上班、摸鱼、加班相关的调侃或感悟）。
    什么时候用：用户说"打工人的话""上班好累""来句职场鸡汤"。"""
    try:
        # 返回字段: ["result"]["content"] - 只提取名言中的内容部分 特点: 专门用于职场励志或心灵鸡汤场景
        return requests.get(f"https://whyta.cn/api/tx/lzmy?key={TOKEN}", timeout=5).json()["result"]["content"]
    except:
        return []
