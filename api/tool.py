# https://apis.whyta.cn/
import logging
import os
from typing import Annotated, Union
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

# 一个实用工具 MCP 服务器，为 AI 助手提供了 6 个实用的查询功能

from fastmcp import FastMCP
mcp = FastMCP(
    name="Tools-MCP-Server",
    instructions="""This server contains some api of tools.""",
)

@mcp.tool(tags={"通用工具"})
def get_city_weather(city_name: Annotated[str, "城市名的拼音，例如 beijing / shanghai / hangzhou。用户说中文城市名时先转成拼音"]):
    """查询某个城市的实时天气，返回温度、体感温度、湿度、风力、天气现象等。
    什么时候用：用户问"今天天气怎么样""上海热不热""要不要带伞""明天冷不冷"。
    什么时候别用：与天气无关的问题不要调用（查股票、查新闻用别的工具）。"""
    try:
        return requests.get(f"https://whyta.cn/api/tianqi?key={TOKEN}&city={city_name}", timeout=5).json()["data"]
    except Exception as e:
        logger.warning("get_city_weather failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"通用工具"})
def get_address_detail(address_text: Annotated[str, "要解析的完整地址文本，例如「浙江省杭州市西湖区文三路 100 号」。注意：要传完整地址，不是只传城市名"]):
    """解析一段地址文本，拆出省、市、区、街道等结构化成份。
    什么时候用：用户给出一段地址，想拆开看它属于哪个省市区，或者要规范化地址。
    什么时候别用：只是想查天气（用 get_city_weather）、只是问城市名。"""
    try:
        return requests.get(f"https://whyta.cn/api/tx/addressparse?key={TOKEN}&text={address_text}", timeout=5).json()["result"]
    except Exception as e:
        logger.warning("get_address_detail failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"通用工具"})
def get_tel_info(tel_no: Annotated[str, "11 位手机号，例如 13800138000"]):
    """查询手机号归属地和运营商。
    什么时候用：用户给出一个手机号，想知道它是哪个省市的、哪家运营商。"""
    try:
        return requests.get(f"https://whyta.cn/api/tx/mobilelocal?key={TOKEN}&phone={tel_no}", timeout=5).json()["result"]
    except Exception as e:
        logger.warning("get_tel_info failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"通用工具"})
def get_scenic_info(scenic_name: Annotated[str, "景点名称，例如「西湖」「故宫」"]):
    """查询某个景点/旅游景区的信息（简介、等级、地址、开放时间等）。
    什么时候用：用户问某个景点怎么样、值不值得去、在哪儿。
    什么时候别用：查天气用 get_city_weather，查地址解析用 get_address_detail。"""
    # https://apis.whyta.cn/docs/tx-scenic.html
    try:
        return requests.get(f"https://whyta.cn/api/tx/scenic?key={TOKEN}&word={scenic_name}", timeout=5).json()["result"]["list"]
    except Exception as e:
        logger.warning("get_scenic_info failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"通用工具"}) # 花语查询
def get_flower_info(flower_name: Annotated[str, "花名，例如「玫瑰」「向日葵」"]):
    """查询某种花的花语和寓意。
    什么时候用：用户问"XX 的花语是什么""送什么花合适"这类与花语含义相关的问题。"""
    # https://apis.whyta.cn/docs/tx-huayu.html
    try:
        return requests.get(f"https://whyta.cn/api/tx/huayu?key={TOKEN}&word={flower_name}", timeout=5).json()["result"]
    except Exception as e:
        logger.warning("get_flower_info failed: %s", _fail_reason(e))
        return []

@mcp.tool(tags={"通用工具"}) # 货币汇率换算
def get_rate_transform(
    source_coin: Annotated[str, "源货币的三位代码，例如 USD（美元）、CNY（人民币）、JPY（日元）"], 
    aim_coin: Annotated[str, "目标货币的三位代码，例如 EUR、CNY、JPY"], 
    money: Annotated[Union[int, float], "要换算的金额，数字类型"]
):
    """按当前汇率把一种货币换算成另一种。
    什么时候用：用户问"100 美元等于多少人民币""日元换人民币多少钱"这类汇率换算问题。
    注意：货币必须用三位代码（USD/CNY/JPY），中文名要先转成代码。"""
    try:
        return requests.get(f"https://whyta.cn/api/tx/fxrate?key={TOKEN}&fromcoin={source_coin}&tocoin={aim_coin}&money={money}", timeout=5).json()["result"]["money"]
    except Exception as e:
        logger.warning("get_rate_transform failed: %s", _fail_reason(e))
        return []
