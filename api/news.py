import os
import requests
import traceback
TOKEN = os.environ.get("WHYTA_TOKEN", "6d997a997fbf")

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
    """Retrieves a list of today's daily news bulletin items from the external API."""
    try:
        # 1. 发送请求并解析 JSON
        # 2. 精准提取数据列表 (例如 ["result"]["list"])
        # 因为新闻接口参数少（只有一个 Token）且逻辑简单（只是获取），所以用了这种最简短的一行流写法；requests.get()
        # 而股票接口因为逻辑复杂，需要更严谨的写法来保证不出错。
        return requests.get(f"https://whyta.cn/api/tx/bulletin?key={TOKEN}", timeout=5).json()["result"]["list"]
    except:
        # 3. 如果出错（断网、数据格式不对），返回空列表，防止程序崩溃
        return []

@mcp.tool(tags={"新闻聚合"})
def get_douyin_hot_news():
    """Retrieves a list of trending topics or hot news from Douyin (TikTok China) using the API."""
    try:
        return requests.get(f"https://whyta.cn/api/tx/douyinhot?key={TOKEN}", timeout=5).json()["result"]["list"]
    except:
        return []




@mcp.tool(tags={"新闻聚合"})
def get_github_hot_news():
    """Retrieves a list of trending repositories/projects on GitHub using the API."""
    print("\n" + "=" * 50)
    print("[DEBUG] 开始调用 get_github_hot_news")

    url = f"https://whyta.cn/api/github?key={TOKEN}"
    print(f"[DEBUG] 请求 URL: {url}")

    try:
        response = requests.get(url, timeout=10)
        print(f"[DEBUG] 响应状态码: {response.status_code}")

        # 如果不是 200，打印错误信息
        if response.status_code != 200:
            print(f"[ERROR] HTTP 错误: {response.status_code}")
            print(f"[ERROR] 响应内容: {response.text[:500]}")
            return []

        # 尝试解析 JSON
        data = response.json()
        print(f"[DEBUG] JSON 解析成功，顶层字段: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")

        # 检查是否有 items 字段
        if "items" in data:
            items = data["items"]
            print(f"[DEBUG] 成功获取 {len(items)} 条 GitHub 热点数据")
            return items
        else:
            print(f"[ERROR] 响应中没有 'items' 字段")
            print(f"[ERROR] 实际响应结构: {data}")
            return []

    except requests.exceptions.Timeout:
        print("[ERROR] 请求超时（超过10秒）")
        traceback.print_exc()
        return []

    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] 连接错误: {e}")
        traceback.print_exc()
        return []

    except Exception as e:
        print(f"[ERROR] 未知错误: {type(e).__name__}: {e}")
        traceback.print_exc()
        return []

@mcp.tool(tags={"新闻聚合"})
def get_toutiao_hot_news(): # 今日头条热点
    """Retrieves a list of hot news headlines from Toutiao (a Chinese news platform) using the API."""
    try:
        return requests.get(f"https://whyta.cn/api/tx/topnews?key={TOKEN}", timeout=5).json()["result"]["list"]
    except:
        import traceback
        traceback.print_exc()
        return []

@mcp.tool(tags={"新闻聚合"})
def get_sports_news():
    """Retrieves a list of esports or general sports news items using the external API."""
    try:
        return requests.get(f"https://whyta.cn/api/tx/esports?key={TOKEN}", timeout=5).json()["result"]["newslist"]
    except:
        return []
