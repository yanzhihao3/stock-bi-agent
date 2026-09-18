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
    而 URL 的 query 里含 API key —— 直接记就等于把密钥写进日志。
    所以只取「异常类型 + HTTP 状态码」；KeyError 的文本是字段名（安全）也带上，
    方便区分「上游 4xx」和「上游返回结构变了」。
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status:
        return f"{type(exc).__name__} (HTTP {status})"
    if isinstance(exc, KeyError):
        return f"{type(exc).__name__} missing field {exc}"
    return type(exc).__name__

# 这个代码创建了一个新闻聚合 MCP 服务器，AI 助手可以通过它获取：
# ✅ 每日要闻 抖音热点 GitHub 热门头条 新闻体育/电竞新闻
# 相比之前的股票代码（提供 HTTP API 给开发者调用），这个是专门给 AI 助手提供实时信息查询能力的工具集。

from fastmcp import FastMCP
mcp = FastMCP(
    name="News-MCP-Server",
    instructions="""This server contains some api of news.""",
)

"""
[Tool(name='get_today_daily_news', title=None, description="Retrieves a list of today's daily news bulletin items from the external API.", inputSchema={'properties': {}, 'type': 'object'}, outputSchema=None, icons=None, annotations=None, meta={'_fastmcp': {'tags': []}})
"""

@mcp.tool(tags={"新闻聚合"}) # # 装饰器，声明这是一个AI可调用的工具
def get_today_daily_news():
    """获取今天的时政财经要闻简报（每日大事汇总）。
    什么时候用：用户问"今天有什么新闻""最近发生什么大事""有什么要闻"。
    什么时候别用：问娱乐热搜用 get_douyin_hot_news，问技术热点用 get_github_hot_news，
                  问社会综合热点用 get_toutiao_hot_news，问比赛用 get_sports_news。"""
    try:
        # 1. 发送请求并解析 JSON
        # 2. 精准提取数据列表 (例如 ["result"]["list"])
        # 因为新闻接口参数少（只有一个 Token）且逻辑简单（只是获取），所以用了这种最简短的一行流写法；requests.get()
        # 而股票接口因为逻辑复杂，需要更严谨的写法来保证不出错。
        return requests.get(f"https://whyta.cn/api/tx/bulletin?key={TOKEN}", timeout=5).json()["result"]["list"]
    except Exception as e:
        # 如果出错（断网 / 上游 4xx / 返回结构变了），记下来，但仍返回空列表防止程序崩溃
        logger.warning("get_today_daily_news failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"新闻聚合"})
def get_douyin_hot_news():
    """获取抖音热搜榜（娱乐八卦、网红动态、流行话题）。
    什么时候用：用户问"抖音上在聊什么""有什么娱乐热搜""最近什么梗火"。
    什么时候别用：问正经新闻要闻用 get_today_daily_news。"""
    try:
        return requests.get(f"https://whyta.cn/api/tx/douyinhot?key={TOKEN}", timeout=5).json()["result"]["list"]
    except Exception as e:
        logger.warning("get_douyin_hot_news failed: %s", _fail_reason(e))
        return []




@mcp.tool(tags={"新闻聚合"})
def get_github_hot_news():
    """获取 GitHub 热榜（近期最热门的开源项目，技术圈风向）。
    什么时候用：用户问"最近有什么火的开源项目""技术圈在关注什么"。"""
    try:
        response = requests.get(f"https://whyta.cn/api/github?key={TOKEN}", timeout=10)
        if response.status_code != 200:
            # 只记状态码：异常文本和请求 URL 里都带着含 token 的 query，不能进日志
            logger.warning("get_github_hot_news failed: HTTP %s", response.status_code)
            return []
        data = response.json()
        # 上游正常时返回 {"items": [...]}；结构变了就当作没查到，不猜
        items = data.get("items") if isinstance(data, dict) else None
        if not items:
            logger.warning("get_github_hot_news: response has no usable 'items' field")
            return []
        return items
    except Exception as e:
        logger.warning("get_github_hot_news failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"新闻聚合"})
def get_toutiao_hot_news(): # 今日头条热点
    """获取今日头条热榜（社会新闻、综合热点排行）。
    什么时候用：用户问"今天有什么热点""最近大家都在讨论什么"。
    什么时候别用：问时政财经要闻用 get_today_daily_news，问娱乐用 get_douyin_hot_news。"""
    try:
        return requests.get(f"https://whyta.cn/api/tx/topnews?key={TOKEN}", timeout=5).json()["result"]["list"]
    except Exception as e:
        logger.warning("get_toutiao_hot_news failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"新闻聚合"})
def get_sports_news():
    """获取电竞/体育新闻。
    什么时候用：用户问"最近有什么比赛""电竞圈新闻""体育赛事"。"""
    try:
        return requests.get(f"https://whyta.cn/api/tx/esports?key={TOKEN}", timeout=5).json()["result"]["newslist"]
    except Exception as e:
        logger.warning("get_sports_news failed: %s", _fail_reason(e))
        return []
