"""chat_common 公共模块单元测试（不依赖外部 API / Redis / LLM）"""

import json

from services.chat_common import (
    TOOL_CATEGORIES,
    get_category_tools,
    sse_event,
    suggest_categories,
)


class TestSSEEvent:
    def test_message_event(self):
        frame = sse_event("message", {"content": "你好"})
        assert frame.startswith("event: message\n")
        payload = json.loads(frame.split("data: ", 1)[1].strip())
        assert payload == {"content": "你好"}

    def test_error_event(self):
        frame = sse_event("error", {"code": 500, "message": "回答生成失败"})
        assert frame.startswith("event: error\n")
        payload = json.loads(frame.split("data: ", 1)[1].strip())
        assert payload["code"] == 500
        assert payload["message"] == "回答生成失败"

    def test_newlines_escaped_in_payload(self):
        """正文中的换行必须被 JSON 转义，避免破坏 SSE 帧边界"""
        frame = sse_event("message", {"content": "line1\nline2"})
        # 帧中只能有一个帧结束符（末尾的空行）
        assert frame.count("\n\n") == 1
        payload = json.loads(frame.split("data: ", 1)[1].strip())
        assert payload["content"] == "line1\nline2"

    def test_frame_ends_with_blank_line(self):
        frame = sse_event("message", {"content": "hi"})
        assert frame.endswith("\n\n")


class TestToolRouting:
    def test_task_maps_to_categories(self):
        assert suggest_categories("股票分析") == ["股票分析"]
        assert set(suggest_categories("数据BI")) == {"股票分析", "通用工具"}
        assert suggest_categories("通用聊天") == ["名言鸡汤"]

    def test_no_task_returns_all_categories(self):
        assert set(suggest_categories(None)) == set(TOOL_CATEGORIES.keys())
        assert set(suggest_categories("")) == set(TOOL_CATEGORIES.keys())
        assert set(suggest_categories("未知任务")) == set(TOOL_CATEGORIES.keys())

    def test_every_category_has_tools(self):
        for category, tools in TOOL_CATEGORIES.items():
            assert tools
            assert get_category_tools(category) == tools
