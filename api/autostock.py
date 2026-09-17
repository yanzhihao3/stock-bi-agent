"""
https://www.autostock.cn/#/trade/stock
https://s.apifox.cn/c3278b4f-5629-4732-858c-36758ff5d083/api-147275957
"""
import os
TOKEN = os.environ.get("AUTOSTOCK_TOKEN", "")

import logging
# FastMCP = 给 AI 用的工具接口
# FastAPI = 给人用的 HTTP 接口   我这个定义的股票在前端被人用， 然后通过mcp = FastMCP.from_fastapi(app=app)变成工具也被AI用
# 场景1：用户在前端页面查询股票  场景2：用户通过 AI 对话查询股票

import httpx
import json
from datetime import date, timedelta
from typing import Annotated
from typing import Optional, Dict
from fastapi import FastAPI, APIRouter, Query  # type: ignore

from services.schema_normalizer import (
    success_response,
    error_response,
    normalize_stock_code,
    normalize_stock_info,
    normalize_kline,
    normalize_industry_rank,
)
from services.redis_client import cached_get, cached_post

logger = logging.getLogger(__name__)

BASE_TIMEOUT = 10.0
TIMEOUT_5 = 5.0


def _ensure_kline_dates(start_date: Optional[str], end_date: Optional[str]) -> tuple:
    """K线日期兜底：为空时默认最近 90 天到今天（与股票中心页面行为一致）。"""
    if not start_date:
        start_date = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = date.today().strftime("%Y-%m-%d")
    return start_date, end_date


# 内部辅助函数：发起异步 GET 请求
async def async_get(url: str, params: dict = None, timeout: float = BASE_TIMEOUT) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        resp = await client.get(url, params=params)
        return resp.json()


# 内部辅助函数：发起异步 POST 请求
async def async_post(url: str, json: dict = None, timeout: float = BASE_TIMEOUT) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        resp = await client.post(url, json=json)
        return resp.json()


app = FastAPI(
    name="Stock api Server",
    instructions="""This server provides stock basic tools.""",
)


@app.get("/get_stock_code", operation_id="stock_get_codes", tags=["股票分析"])
async def get_all_stock_code(
        keyword: Annotated[Optional[str], Query(description="股票代码或名称的关键字，支持模糊匹配；不传则返回全部股票")] = None
) -> Dict:
    """查询股票代码和名称：按关键字模糊搜索，返回匹配的股票列表。
    什么时候用：用户提到某只股票（如"茅台""贵州茅台"）时，先用这个工具查出它的标准代码，
              其余股票类工具都需要这个 code。
    什么时候别用：查指数用 stock_get_index_code。"""
    url = "https://api.autostock.cn/v1/stock/all" + "?token=" + TOKEN
    if keyword:
        url += "&keyWord=" + keyword
    try:
        raw_data = await cached_get(url, ttl=3600, timeout=BASE_TIMEOUT)
        normalized_data = normalize_stock_code(raw_data)
        return success_response([item.model_dump() for item in normalized_data])
    # model_dump() 就像把一份填写好的表格（对象）提取成纯数据（字典），方便存储或传输。
    except Exception:
        logger.exception("get_stock_code failed")
        return error_response("获取股票代码失败")


@app.get("/get_index_code", operation_id="stock_get_index_code", tags=["股票分析"])
async def get_all_index_code():
    """获取所有市场指数（上证指数、深证成指、创业板指等）的代码和名称。
    什么时候用：用户问"大盘指数""某个指数叫什么代码"。
    注意：这个工具没有搜索参数，会返回全部指数。"""
    url = "https://api.autostock.cn/v1/stock/index/all" + "?token=" + TOKEN
    try:
        raw_data = await cached_get(url, ttl=3600, timeout=TIMEOUT_5)
        normalized_data = normalize_stock_code(raw_data)
        return success_response([item.model_dump() for item in normalized_data])
    except Exception as e:
        logger.exception("get_index_code failed")
        return error_response("获取指数代码失败")


@app.get("/get_industry_code", operation_id="stock_get_industry_code", tags=["股票分析"])
async def get_stock_industry_code():
    """获取行业板块的行情排名（各板块涨跌幅、资金流向）。
    什么时候用：用户问"今天哪个板块涨得好""行业排行""哪个行业最强"。"""
    url = "https://api.autostock.cn/v1/stock/industry/rank" + "?token=" + TOKEN
    try:
        response = await cached_get(url, ttl=600, timeout=TIMEOUT_5)
        return response
    except Exception as e:
        logger.exception("get_industry_code failed")
        return error_response("获取板块数据失败")


@app.get("/get_board_info", operation_id="stock_get_board_info", tags=["股票分析"])
async def get_stock_board_info():
    """获取大盘整体概况（主要指数涨跌、成交额、涨跌家数等市场总览）。
    什么时候用：用户问"今天大盘怎么样""市场整体行情如何"。
    注意：这是整个市场的视角，不针对某只个股。回答大盘问题时，
          用本工具（需要时加 stock_get_industry_code 看板块）就够了，
          不要再调用个股的 K 线类工具。"""
    url = "https://api.autostock.cn/v1/stock/board" + "?token=" + TOKEN
    try:
        raw = await cached_get(url, ttl=300, timeout=TIMEOUT_5)
        board_data = raw.get("data", []) if isinstance(raw, dict) else []
        return success_response(board_data)
    except Exception as e:
        logger.exception("get_board_info failed")
        return error_response("获取大盘数据失败")


@app.get("/get_stock_rank", operation_id="stock_get_rank", tags=["股票分析"])
async def get_stock_rank(
        node: Annotated[str, Query(description="市场代码，必填。可选值：a=沪深A股（默认用途）、b=北交所、ash=沪A、asz=深A、bsh=沪B、bsz=深B")],
        industryCode: Annotated[Optional[str], Query(description="限定行业板块的代码，不传表示不限行业。行业代码可用 stock_get_industry_code 查")] = None,
        pageIndex: Annotated[int, Query(description="页码，从 1 开始")] = 1,
        pageSize: Annotated[int, Query(description="每页返回多少条")] = 100,
        sort: Annotated[str, Query(description="排序字段，例如 price（按价格）")] = "price",
        asc: Annotated[int, Query(description="排序方向：0=降序（默认），1=升序")] = 0
) -> Dict:
    """股票排行榜：按指定字段排序返回股票列表。
    什么时候用：用户问"涨幅榜""今天涨得最好的股票""排行榜前几名"。"""
    url = "https://api.autostock.cn/v1/stock/rank" + "?token=" + TOKEN
    payload = {
        "node": node,
        "industryCode": industryCode,
        "pageIndex": pageIndex,
        "pageSize": pageSize,
        "sort": sort,
        "asc": asc
    }
    try:
        return await cached_post(url, json_data=payload, ttl=60, timeout=TIMEOUT_5)
    except Exception as e:
        logger.exception("get_stock_rank failed")
        return {}


@app.get("/get_month_line", operation_id="stock_get_month_line", tags=["股票分析"])
async def get_stock_month_kline(
        code: Annotated[str, Query(description="股票代码，必须先用 stock_get_codes 查出标准代码")],
        startDate: Annotated[Optional[str], Query(description="开始日期，格式 YYYY-MM-DD；不传默认最近 90 天")] = None,
        endDate: Annotated[Optional[str], Query(description="结束日期，格式 YYYY-MM-DD；不传默认今天")] = None,
        type: Annotated[int, Query(description="复权方式：0=不复权（默认），1=前复权，2=后复权")] = 0
) -> Dict:
    """获取月 K 线（每月一根），适合看长期趋势。
    什么时候用：用户想看几年的大趋势、长期走势。
    什么时候别用：看近期走势用 stock_get_day_line，看中期用 stock_get_week_line。"""
    startDate, endDate = _ensure_kline_dates(startDate, endDate)
    url = "https://api.autostock.cn/v1/stock/kline/month" + "?token=" + TOKEN
    try:
        raw_data = await cached_get(url, params={"code": code, "startDate": startDate, "endDate": endDate, "type": type}, ttl=600, timeout=BASE_TIMEOUT)
        normalized_data = normalize_kline(raw_data)
        return success_response([item.model_dump() for item in normalized_data])
    except Exception:
        logger.exception("get_month_line failed")
        return error_response("获取月K线数据失败")


@app.get("/get_week_line", operation_id="stock_get_week_line", tags=["股票分析"])
async def get_stock_week_kline(
        code: Annotated[str, Query(description="股票代码，必须先用 stock_get_codes 查出标准代码")],
        startDate: Annotated[Optional[str], Query(description="开始日期，格式 YYYY-MM-DD；不传默认最近 90 天")] = None,
        endDate: Annotated[Optional[str], Query(description="结束日期，格式 YYYY-MM-DD；不传默认今天")] = None,
        type: Annotated[int, Query(description="复权方式：0=不复权（默认），1=前复权，2=后复权")] = 0
):
    """获取周 K 线（每周一根），适合看中期趋势。
    什么时候用：用户想看最近几个月到一两年的走势。
    什么时候别用：看长期用 stock_get_month_line，看短期用 stock_get_day_line。"""
    startDate, endDate = _ensure_kline_dates(startDate, endDate)
    url = "https://api.autostock.cn/v1/stock/kline/week" + "?token=" + TOKEN
    try:
        raw_data = await cached_get(url, params={"code": code, "startDate": startDate, "endDate": endDate, "type": type}, ttl=600, timeout=BASE_TIMEOUT)
        normalized_data = normalize_kline(raw_data)
        return success_response([item.model_dump() for item in normalized_data])
    except Exception:
        logger.exception("get_week_line failed")
        return error_response("获取周K线数据失败")


@app.get("/get_day_line", operation_id="stock_get_day_line", tags=["股票分析"])
async def get_stock_day_kline(
        code: Annotated[str, Query(description="股票代码，必须先用 stock_get_codes 查出标准代码")],
        startDate: Annotated[Optional[str], Query(description="开始日期，格式 YYYY-MM-DD；不传默认最近 90 天")] = None,
        endDate: Annotated[Optional[str], Query(description="结束日期，格式 YYYY-MM-DD；不传默认今天")] = None,
        type: Annotated[int, Query(description="复权方式：0=不复权（默认），1=前复权，2=后复权")] = 0
) -> Dict:
    """获取「某一只具体股票」的日 K 线（每天一根）。
    使用前提：必须已经拿到具体的股票代码。用户只说了公司名（如"贵州茅台"）时，
              先用 stock_get_codes 查到代码，再调用本工具。
    什么时候用：用户问某只股票的"最近走势""近一个月涨了多少"。
    什么时候别用：
      - 问大盘、指数、板块行情 → 用 stock_get_board_info / stock_get_index_code / stock_get_industry_code
      - 问公司资料、市值、市盈率等基本面 → 用 stock_get_info
      - 看更长跨度 → stock_get_week_line / stock_get_month_line；看当天盘中 → stock_get_minute_data
    本工具必须带 code 参数；没有具体股票代码就不要调用。"""
    startDate, endDate = _ensure_kline_dates(startDate, endDate)
    url = "https://api.autostock.cn/v1/stock/kline/day" + "?token=" + TOKEN
    try:
        raw_data = await cached_get(url, params={"code": code, "startDate": startDate, "endDate": endDate, "type": type}, ttl=300, timeout=BASE_TIMEOUT)
        normalized_data = normalize_kline(raw_data)
        return success_response([item.model_dump() for item in normalized_data])
    except Exception:
        logger.exception("get_day_line failed")
        return error_response("获取日K线数据失败")


@app.get("/get_stock_info", operation_id="stock_get_info", tags=["股票分析"])
async def get_stock_info(code: Annotated[str, Query(description="股票代码，必须先用 stock_get_codes 查出标准代码")]) -> Dict:
    """获取股票的基础信息（公司名称、所属行业、市值、市盈率等基本面数据）。
    什么时候用：用户问"这家公司是做什么的""市值多少""市盈率多少""基本面怎么样"。
    提示：问基本面时，"查到代码 + 本工具"就够了，不需要再查 K 线行情数据。"""
    url = "https://api.autostock.cn/v1/stock" + "?token=" + TOKEN + "&code=" + code
    try:
        raw_data = await cached_get(url, ttl=600, timeout=BASE_TIMEOUT)
        normalized_data = normalize_stock_info(raw_data)
        if normalized_data:
            return success_response(normalized_data.model_dump())
        return error_response("未找到股票信息")
    except Exception:
        logger.exception("get_stock_info failed")
        return error_response("获取股票信息失败")


@app.get("/get_stock_minute_data", operation_id="stock_get_minute_data", tags=["股票分析"])
async def get_stock_minute_data(code: Annotated[str, Query(description="股票代码，必须先用 stock_get_codes 查出标准代码")]):
    """获取当日的分时数据（盘中每分钟的价格与成交量走势）。
    什么时候用：用户问"今天的盘中走势""分时图""现在什么价格"。
    什么时候别用：看历史走势用 stock_get_day_line。"""
    url = "https://api.autostock.cn/v1/stock/min" + "?token=" + TOKEN + "&code=" + code
    try:
        raw = await cached_get(url, ttl=30, timeout=BASE_TIMEOUT)
        data = raw.get("data", {}) if isinstance(raw, dict) else {}
        min_data = data.get("minData", []) if isinstance(data, dict) else []
        info = {k: v for k, v in data.items() if k != "minData"}
        result = {**info, "minData": min_data}
        return success_response(result)
    except Exception:
        logger.exception("get_stock_minute_data failed")
        return error_response("获取分时数据失败")
