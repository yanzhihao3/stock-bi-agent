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
from fastapi import FastAPI, APIRouter  # type: ignore

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
        keyword: Annotated[Optional[str], "支持代码和名称模糊查询"] = None
) -> Dict:
    """所有股票，支持代码和名称模糊查询"""
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
    """所有指数，支持代码和名称模糊查询"""
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
    """获取板块数据"""
    url = "https://api.autostock.cn/v1/stock/industry/rank" + "?token=" + TOKEN
    try:
        response = await cached_get(url, ttl=600, timeout=TIMEOUT_5)
        return response
    except Exception as e:
        logger.exception("get_industry_code failed")
        return error_response("获取板块数据失败")


@app.get("/get_board_info", operation_id="stock_get_board_info", tags=["股票分析"])
async def get_stock_board_info():
    """获取大盘数据"""
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
        node: Annotated[str, "股票市场/板块代码: {'a','b','ash','asz','bsh','bsz'} a(沪深A股)"],
        industryCode: Annotated[Optional[str], "行业代码，可选"] = None,
        pageIndex: Annotated[int, "页码"] = 1,
        pageSize: Annotated[int, "每页大小"] = 100,
        sort: Annotated[str, "排序字段"] = "price",
        asc: Annotated[int, "排序方式: 0=降序(默认), 1=升序"] = 0
) -> Dict:
    """股票排行"""
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
        code: Annotated[str, "股票代码"],
        startDate: Annotated[Optional[str], "开始时间(非必填)"] = None,
        endDate: Annotated[Optional[str], "结束时间(非必填)"] = None,
        type: Annotated[int, "0不复权,1前复权,2后复权"] = 0
) -> Dict:
    """月k"""
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
        code: Annotated[str, "股票代码"],
        startDate: Annotated[Optional[str], "开始时间(非必填)"] = None,
        endDate: Annotated[Optional[str], "结束时间(非必填)"] = None,
        type: Annotated[int, "0不复权,1前复权,2后复权"] = 0
):
    """周k"""
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
        code: Annotated[str, "股票代码"],
        startDate: Annotated[Optional[str], "开始时间(非必填)"] = None,
        endDate: Annotated[Optional[str], "结束时间(非必填)"] = None,
        type: Annotated[int, "0不复权,1前复权,2后复权"] = 0
) -> Dict:
    """日k"""
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
async def get_stock_info(code: Annotated[str, "股票代码"]) -> Dict:
    """股票基础信息"""
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
async def get_stock_minute_data(code: str):
    """分时信息"""
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
