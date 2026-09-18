import logging
import os
import requests
TOKEN = os.environ.get("WHYTA_TOKEN", "")

logger = logging.getLogger(__name__)
# 说明：下面每个工具都保持「出错就返回空列表」的降级行为，用户体验不变
# （只会看到"没查到"），但不再用裸 except 静默吞掉 —— 失败会记一条 warning，
# 这样翻日志就能区分「上游挂了」和「真的没有数据」。


def _fail_reason(exc: Exception) -> str:
    """把异常压成一行可安全记录的文本。

    ⚠️ 不能直接记 str(exc)：requests 的异常文本里带着**完整请求 URL**，
    而 URL 的 query 里含 API key —— 直接记就等于把密钥写进日志，
    日志一旦被分享（贴给别人排错）就是泄漏。
    所以这里只取「异常类型 + HTTP 状态码」；KeyError 的文本是字段名（安全）也带上，
    方便区分「上游 4xx」和「上游返回结构变了」。
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status:
        return f"{type(exc).__name__} (HTTP {status})"
    if isinstance(exc, KeyError):
        return f"{type(exc).__name__} missing field {exc}"
    return type(exc).__name__

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
    except Exception as e:
        logger.warning("get_today_familous_saying failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"名言鸡汤"})
def get_today_motivation_saying():
    """返回一句励志语录（打气、正能量）。
    什么时候用：用户说"鼓励我一下""说句励志的话""心情不好想听点积极的话"。"""
    try:
        # 返回字段: ["result"] - 励志名言（可能包含标题、内容、作者等） 特点: 返回完整的励志句子对象
        return requests.get(f"https://whyta.cn/api/tx/lzmy?key={TOKEN}", timeout=5).json()["result"]
    except Exception as e:
        logger.warning("get_today_motivation_saying failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"名言鸡汤"})
def get_today_working_saying():
    """返回一句职场/打工主题的语录（上班、摸鱼、加班相关的调侃或感悟）。
    什么时候用：用户说"打工人的话""上班好累""来句职场鸡汤"。"""
    try:
        # 返回字段: ["result"]["content"] - 只提取名言中的内容部分 特点: 专门用于职场励志或心灵鸡汤场景
        return requests.get(f"https://whyta.cn/api/tx/lzmy?key={TOKEN}", timeout=5).json()["result"]["content"]
    except Exception as e:
        logger.warning("get_today_working_saying failed: %s", _fail_reason(e))
        return []
