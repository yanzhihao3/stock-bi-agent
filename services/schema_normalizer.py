"""
统一响应 Schema 规范化治理
实现 API 响应统一 Schema 规范化，与 Plotly 可视化渲染联动
"""

from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from models.data_models import (
    ApiResponse,
    StockCodeItem,
    StockInfoItem,
    KLineItem,
    IndustryRankItem,
    NewsItem,
    WeatherItem,
)


def success_response(data: Any, message: str = "success") -> Dict:
    """统一成功响应"""
    return ApiResponse(code=200, message=message, data=data).model_dump()


def error_response(message: str, code: int = 400) -> Dict:
    """统一错误响应"""
    return ApiResponse(code=code, message=message, data=None).model_dump()


def normalize_stock_code(raw_data: Any) -> List[StockCodeItem]:
    """规范化股票代码响应"""
    if not raw_data:
        return []

    items = []
    data_list = raw_data.get("data", []) if isinstance(raw_data, dict) else raw_data

    for item in data_list:
        if isinstance(item, dict):
            items.append(StockCodeItem(
                code=item.get("code", ""),
                name=item.get("name", ""),
                market=item.get("market")
            ))
        elif isinstance(item, list) and len(item) >= 2:
            items.append(StockCodeItem(code=str(item[0]), name=str(item[1])))

    return items


def normalize_stock_info(raw_data: Any) -> Optional[StockInfoItem]:
    """规范化股票详细信息响应"""
    if not raw_data:
        return None

    data = raw_data.get("data", {}) if isinstance(raw_data, dict) else raw_data

    # 外部 API 返回的 data 可能是列表（第一个元素是股票详情对象）
    if isinstance(data, list):
        data = data[0] if data else {}

    if isinstance(data, dict):
        return StockInfoItem(
            code=data.get("code", ""),
            name=data.get("name", ""),
            open=data.get("open"),
            close=data.get("close"),
            high=data.get("high"),
            low=data.get("low"),
            volume=data.get("volume"),
            turnover=data.get("turnover"),
            pe=data.get("pe"),
            market_cap=data.get("market_cap")
        )
    return None


def normalize_kline(raw_data: Any) -> List[KLineItem]:
    """规范化K线数据响应（大模型友好结构化上下文）"""
    if not raw_data:
        return []

    items = []
    data_list = raw_data.get("data", []) if isinstance(raw_data, dict) else raw_data

    for item in data_list:
        if isinstance(item, list) and len(item) >= 6:
            items.append(KLineItem(
                date=str(item[0]),
                open=float(item[2]) if item[2] else 0.0,
                close=float(item[1]) if item[1] else 0.0,
                high=float(item[3]) if item[3] else 0.0,
                low=float(item[4]) if item[4] else 0.0,
                volume=float(item[5]) if item[5] else 0.0,
                turnover=float(item[6]) if len(item) > 6 and item[6] and isinstance(item[6], (int, float, str)) and item[6].replace('.', '', 1).replace('-', '', 1).isdigit() else None
            ))
        elif isinstance(item, dict):
            items.append(KLineItem(
                date=item.get("date", ""),
                open=float(item.get("open", 0)),
                close=float(item.get("close", 0)),
                high=float(item.get("high", 0)),
                low=float(item.get("low", 0)),
                volume=float(item.get("volume", 0)),
                turnover=item.get("turnover")
            ))

    return items


def normalize_industry_rank(raw_data: Any) -> List[IndustryRankItem]:
    """规范化行业板块排行响应"""
    if not raw_data:
        return []

    items = []
    data_list = raw_data.get("data", []) if isinstance(raw_data, dict) else raw_data

    for item in data_list:
        if isinstance(item, dict):
            # 处理编码问题：检测 name 是否为乱码（GBK 被当成 UTF-8），如果是则转换
            name = item.get("name", "")
            if name and "" in name:
                # 尝试用 GBK 解码后再用 UTF-8 编码回去
                try:
                    name = name.encode('latin1').decode('gbk')
                except Exception:
                    pass

            items.append(IndustryRankItem(
                code=item.get("industryCode", ""),  # API 返回的是 industryCode，不是 code
                name=name,
                change=item.get("change"),
                volume=item.get("volume"),
                lead_stock=item.get("lead_stock")
            ))
        elif isinstance(item, list) and len(item) >= 4:
            items.append(IndustryRankItem(
                code=str(item[0]),
                name=str(item[1]),
                change=float(item[2]) if item[2] else None,
                volume=float(item[3]) if item[3] else None
            ))

    return items


def normalize_news(raw_data: Any) -> List[NewsItem]:
    """规范化新闻响应"""
    if not raw_data:
        return []

    items = []
    data_list = raw_data if isinstance(raw_data, list) else raw_data.get("data", [])

    for item in data_list:
        if isinstance(item, dict):
            items.append(NewsItem(
                title=item.get("title", ""),
                content=item.get("content"),
                source=item.get("source"),
                publish_time=item.get("publish_time")
            ))
        elif isinstance(item, list) and len(item) >= 2:
            items.append(NewsItem(title=str(item[0]), content=str(item[1]) if len(item) > 1 else None))

    return items


def normalize_weather(raw_data: Any) -> Optional[WeatherItem]:
    """规范化天气响应"""
    if not raw_data:
        return None

    data = raw_data if isinstance(raw_data, dict) else {"data": raw_data}
    weather_data = data.get("data", data)

    if isinstance(weather_data, dict):
        return WeatherItem(
            city=weather_data.get("city", ""),
            weather=weather_data.get("weather", ""),
            temperature=weather_data.get("temperature", ""),
            humidity=weather_data.get("humidity"),
            wind=weather_data.get("wind")
        )
    return None
