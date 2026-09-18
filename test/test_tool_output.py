"""工具返回判定的测试

这些用例的形状全部来自真实返回（尤其是 K 线那条静默失败）。
它们是这套判定的"真值表"—— 判定规则改了，先看这里哪条挂了。
"""

import json
import logging

from services.chat_common import log_tool_result, summarize_tool_output


def _mcp_wrap(payload) -> str:
    """复刻 fastmcp 的包装：{"type": "text", "text": "<json 字符串>"}"""
    return json.dumps({"type": "text", "text": json.dumps(payload, ensure_ascii=False)})


class TestSummarizeToolOutput:
    def test_kline_empty_data_is_flagged(self):
        """实测的原型：HTTP 200 + success + data:[] —— 这就是那个没人发现的故障。"""
        raw = _mcp_wrap({"code": 200, "message": "success", "data": []})
        summary = summarize_tool_output(raw)
        assert summary["empty"] is True
        assert summary["error"] is False
        assert summary["reason"] == "data 为空"

    def test_error_response_is_flagged(self):
        """api/*.py 的 error_response：code 非 200、data 为 None。"""
        raw = _mcp_wrap({"code": 400, "message": "获取日K线数据失败", "data": None})
        summary = summarize_tool_output(raw)
        assert summary["error"] is True
        assert "code=400" in summary["reason"]
        assert "获取日K线数据失败" in summary["reason"]

    def test_bare_empty_list_is_flagged(self):
        """api/news.py 失败时直接返回 []，没有业务包装层。"""
        assert summarize_tool_output([])["empty"] is True

    def test_empty_string_is_flagged(self):
        assert summarize_tool_output("   ")["empty"] is True

    def test_none_is_flagged(self):
        summary = summarize_tool_output(None)
        assert summary["empty"] is True
        assert summary["size"] == 0

    def test_data_none_is_empty(self):
        assert summarize_tool_output({"code": 200, "data": None})["empty"] is True

    def test_data_empty_dict_is_empty(self):
        assert summarize_tool_output({"code": 200, "data": {}})["empty"] is True

    def test_normal_payload_passes(self):
        raw = _mcp_wrap({"code": 200, "message": "success",
                         "data": [{"code": "sh600519", "name": "贵州茅台"}]})
        summary = summarize_tool_output(raw)
        assert summary["empty"] is False
        assert summary["error"] is False
        assert summary["size"] > 0

    def test_unwrapped_dict_passes(self):
        """天气工具直接返回上游 dict，没有 code/data 包装。"""
        summary = summarize_tool_output({"temp_C": "27", "humidity": "63"})
        assert summary["empty"] is False
        assert summary["error"] is False

    def test_plain_text_tool_passes(self):
        """名言类工具返回纯文本，不是 JSON。"""
        summary = summarize_tool_output("今天也要加油鸭～")
        assert summary["empty"] is False
        assert summary["error"] is False

    def test_non_json_text_is_not_treated_as_error(self):
        """解析不了 ≠ 出错：有的工具本来就返回非 JSON，不能冤枉它们。"""
        summary = summarize_tool_output("这是一个不是 JSON 的返回")
        assert summary["error"] is False

    def test_size_reflects_raw_length(self):
        raw = _mcp_wrap({"code": 200, "data": []})
        assert summarize_tool_output(raw)["size"] == len(raw)


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


class TestLogToolResult:
    @staticmethod
    def _capture(monkeypatch):
        handler = _Capture()
        logger = logging.getLogger("services.chat_common")
        monkeypatch.setattr(logger, "handlers", [handler])
        monkeypatch.setattr(logger, "propagate", False)
        return handler

    def test_logs_when_empty(self, monkeypatch):
        handler = self._capture(monkeypatch)
        log_tool_result("stock_get_kline", {"code": "sh600519"},
                        summarize_tool_output({"code": 200, "data": []}))
        assert len(handler.records) == 1
        message = handler.records[0]
        assert "status=empty" in message
        assert "tool=stock_get_kline" in message
        assert "sh600519" in message  # 参数摘要进日志，方便定位是哪只股票

    def test_logs_when_error(self, monkeypatch):
        handler = self._capture(monkeypatch)
        log_tool_result("get_today_daily_news", None,
                        summarize_tool_output({"code": 503, "message": "上游挂了"}))
        assert len(handler.records) == 1
        assert "status=error" in handler.records[0]

    def test_silent_when_ok(self, monkeypatch):
        """正常的返回不能刷日志 —— 否则工具调用越多日志越吵。"""
        handler = self._capture(monkeypatch)
        log_tool_result("get_city_weather", {"city_name": "shanghai"},
                        summarize_tool_output({"temp_C": "27"}))
        assert handler.records == []

    def test_does_not_log_the_body(self, monkeypatch):
        """content-free：日志里不能出现返回正文（正文只该在 traces.jsonl 里）。"""
        handler = self._capture(monkeypatch)
        # 构造一个"会记日志、但返回体很大"的场景：data 为空 → 记 empty
        raw = json.dumps({"code": 200, "message": "success", "data": [],
                          "raw": "X" * 500})
        log_tool_result("stock_get_kline", {"code": "sh600519"},
                        summarize_tool_output(raw))
        assert len(handler.records) == 1
        assert "XXXX" not in handler.records[0]
