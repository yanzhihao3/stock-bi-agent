"""eval/report.py 的统计逻辑测试

锁住两条容易说反的规矩（都是开发时真踩到的）：
  1. 老轨迹缺判定字段时不能默认当成"正常"——否则真有故障时报表显示一切健康
  2. "受影响的对话"要按对话数算，不能按工具调用数算——一次对话连调三次全空，
     对用户是一次糟糕体验，不是三次
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("report", ROOT / "eval" / "report.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)


def _record(question="q", engine="agents", tools=None, elapsed=1000, body=100, **extra):
    record = {
        "engine": engine,
        "question": question,
        "session_id": "SESS-1",
        "elapsed_ms": elapsed,
        "body_chars": body,
        "tool_results": tools,
    }
    record.update(extra)
    return record


def _tool(name="t", empty=False, error=False, decided=True):
    item = {"name": name, "output": "x", "size": 1}
    if decided:
        item["empty"] = empty
        item["error"] = error
    return item


class TestCollect:
    def test_legacy_record_is_not_counted_as_healthy(self):
        """没有 tool_results 字段的老轨迹，既不算健康也不算故障，单独计数。"""
        stats = rp.collect([_record(tools=None)])
        assert stats["legacy"] == 1
        assert stats["tool_calls"] == 0
        assert stats["tool_empty"] == 0
        assert stats["affected_records"] == 0
        assert stats["decided_records"] == 0

    def test_item_without_judgement_field_is_undecided(self):
        """有 tool_results 但项里没有 empty 字段（加字段之前的轨迹）→ 未判定。"""
        stats = rp.collect([_record(tools=[_tool(decided=False)])])
        assert stats["tool_calls"] == 1
        assert stats["tool_undecided"] == 1
        assert stats["tool_empty"] == 0        # 关键：不能算成"正常"
        assert stats["affected_records"] == 0

    def test_empty_tool_call_counted(self):
        stats = rp.collect([_record(tools=[_tool(name="k", empty=True)])])
        assert stats["tool_empty"] == 1
        assert stats["affected_records"] == 1

    def test_error_tool_call_counted(self):
        stats = rp.collect([_record(tools=[_tool(name="k", error=True)])])
        assert stats["tool_error"] == 1
        assert stats["affected_records"] == 1

    def test_affected_counts_conversations_not_calls(self):
        """一次对话里连调三次全空 → 受影响的是 1 条对话，不是 3 条。"""
        record = _record(tools=[
            _tool(name="k", empty=True),
            _tool(name="k", empty=True),
            _tool(name="k", empty=True),
        ])
        stats = rp.collect([record])
        assert stats["tool_empty"] == 3
        assert stats["affected_records"] == 1
        assert stats["decided_records"] == 1

    def test_healthy_conversation_not_affected(self):
        stats = rp.collect([_record(tools=[_tool(name="weather")])])
        assert stats["affected_records"] == 0
        assert stats["tool_empty"] == 0
        assert stats["tools"]["weather"]["calls"] == 1

    def test_tool_stats_aggregate_across_records(self):
        stats = rp.collect([
            _record(tools=[_tool(name="k", empty=True)]),
            _record(tools=[_tool(name="k")]),
        ])
        assert stats["tools"]["k"] == {"calls": 2, "empty": 1, "error": 0}

    def test_engine_denominator_ignores_legacy_records(self):
        """按引擎算平均工具数时，分母只能用"有判定字段的轨迹"，
        否则老轨迹会把平均值拉成 0，看着像"模型从不调工具"。"""
        stats = rp.collect([
            _record(tools=None),                        # 老轨迹
            _record(tools=[_tool(), _tool(), _tool()]),  # 3 个工具
        ])
        agents = stats["by_engine"]["agents"]
        assert agents["count"] == 2
        assert agents["decided_records"] == 1
        assert agents["tools"] == 3

    def test_time_window_tracks_first_and_last(self):
        stats = rp.collect([
            _record(ts="2026-09-19T10:00:00"),
            _record(ts="2026-09-17T08:00:00"),
            _record(ts="2026-09-18T12:00:00"),
        ])
        assert stats["first_ts"] == "2026-09-17T08:00:00"
        assert stats["last_ts"] == "2026-09-19T10:00:00"


class TestToolsDesc:
    def test_marks_empty_and_error(self):
        record = _record(tools=[_tool(name="k", empty=True), _tool(name="n", error=True)])
        assert rp._tools_desc(record) == "k[空], n[错]"

    def test_plain_tool_has_no_mark(self):
        assert rp._tools_desc(_record(tools=[_tool(name="weather")])) == "weather"

    def test_no_tool_called(self):
        assert rp._tools_desc(_record(tools=[])) == "未调用工具"

    def test_legacy_record_says_so(self):
        assert "老轨迹" in rp._tools_desc(_record(tools=None))


class TestHelpers:
    def test_percentile_edges(self):
        values = [10, 20, 30, 40, 50]
        assert rp.percentile(values, 0.0) == 10
        assert rp.percentile(values, 1.0) == 50
        assert rp.percentile(values, 0.5) == 30

    def test_percentile_empty(self):
        assert rp.percentile([], 0.5) == 0.0

    def test_window_same_day_collapses_date(self):
        text = rp._window("2026-09-19T10:00:00", "2026-09-19T11:30:00")
        assert text == "2026-09-19 10:00 ~ 11:30"

    def test_window_cross_day_shows_both(self):
        text = rp._window("2026-09-17T10:00:00", "2026-09-19T11:30:00")
        assert "T" not in text
        assert text == "2026-09-17 10:00 ~ 2026-09-19 11:30"
