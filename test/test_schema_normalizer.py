"""schema_normalizer 单元测试（不依赖外部 API）"""

import pytest
from services.schema_normalizer import (
    success_response,
    error_response,
    normalize_stock_code,
    normalize_stock_info,
    normalize_kline,
    normalize_news,
    normalize_weather,
)


class TestSuccessResponse:
    def test_with_data(self):
        result = success_response([{"key": "value"}])
        assert result["code"] == 200
        assert result["message"] == "success"
        assert result["data"] == [{"key": "value"}]
        assert "timestamp" in result

    def test_with_none(self):
        result = success_response(None)
        assert result["code"] == 200
        assert result["data"] is None


class TestErrorResponse:
    def test_default_error(self):
        result = error_response("出错了")
        assert result["code"] == 400
        assert result["message"] == "出错了"
        assert result["data"] is None

    def test_custom_code(self):
        result = error_response("服务器错误", code=500)
        assert result["code"] == 500


class TestNormalizeStockCode:
    def test_dict_list_input(self):
        raw = {"data": [{"code": "sh600519", "name": "贵州茅台"}, {"code": "sz000001", "name": "平安银行"}]}
        items = normalize_stock_code(raw)
        assert len(items) == 2
        assert items[0].code == "sh600519"
        assert items[0].name == "贵州茅台"
        assert items[1].code == "sz000001"

    def test_list_input(self):
        raw = [{"code": "sh600519", "name": "贵州茅台"}]
        items = normalize_stock_code(raw)
        assert len(items) == 1
        assert items[0].code == "sh600519"

    def test_empty_input(self):
        assert normalize_stock_code(None) == []
        assert normalize_stock_code({}) == []


class TestNormalizeStockInfo:
    def test_dict_data(self):
        raw = {"data": {"code": "sh600519", "name": "贵州茅台", "open": 1800.0}}
        info = normalize_stock_info(raw)
        assert info is not None
        assert info.code == "sh600519"
        assert info.name == "贵州茅台"
        assert info.open == 1800.0

    def test_list_data(self):
        raw = {"data": [{"code": "sh600519", "name": "贵州茅台", "open": 1800.0}]}
        info = normalize_stock_info(raw)
        assert info is not None
        assert info.code == "sh600519"

    def test_empty_input(self):
        assert normalize_stock_info(None) is None
        assert normalize_stock_info({}) is None


class TestNormalizeKline:
    def test_list_of_lists(self):
        raw = {"data": [
            ["2024-01-02", 1700.0, 1690.0, 1710.0, 1680.0, 10000],
            ["2024-01-03", 1710.0, 1700.0, 1720.0, 1690.0, 12000],
        ]}
        items = normalize_kline(raw)
        assert len(items) == 2
        assert items[0].date == "2024-01-02"
        assert items[0].open == 1690.0
        assert items[0].close == 1700.0
        assert items[0].high == 1710.0
        assert items[0].low == 1680.0
        assert items[0].volume == 10000

    def test_list_of_dicts(self):
        raw = {"data": [
            {"date": "2024-01-02", "open": 1690, "close": 1700, "high": 1710, "low": 1680, "volume": 10000},
        ]}
        items = normalize_kline(raw)
        assert len(items) == 1
        assert items[0].open == 1690.0

    def test_empty_input(self):
        assert normalize_kline(None) == []


class TestNormalizeNews:
    def test_dict_list(self):
        raw = {"data": [
            {"title": "新闻1", "content": "内容1", "source": "来源A"},
            {"title": "新闻2"},
        ]}
        items = normalize_news(raw)
        assert len(items) == 2
        assert items[0].title == "新闻1"
        assert items[0].source == "来源A"
        assert items[1].title == "新闻2"

    def test_empty_input(self):
        assert normalize_news(None) == []


class TestNormalizeWeather:
    def test_dict_data(self):
        raw = {"data": {"city": "北京", "weather": "晴", "temperature": "25°C"}}
        weather = normalize_weather(raw)
        assert weather is not None
        assert weather.city == "北京"
        assert weather.weather == "晴"

    def test_empty_input(self):
        assert normalize_weather(None) is None
