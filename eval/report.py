#!/usr/bin/env python
"""可观测性报告 —— 从运行轨迹汇总延迟 / token / 工具健康度

用法
    python eval/report.py
    python eval/report.py --trace-path logs/eval-traces.jsonl
    python eval/report.py --limit 50 --engine agents
    python eval/report.py --tools 10              # 最多列 10 个工具
    python eval/report.py --all-tools             # 正常的工具也列出来

它在回答什么问题
    「最近这段时间，我的 AI 应用健康吗？」
    —— 延迟有没有变慢、token 有没有涨、哪个工具在悄悄返回空。

为什么这张表值得存在（真实来历）
    K 线接口曾经静默返回 `{"code":200,"message":"success","data":[]}`：
    HTTP 200、不抛异常、日志里一条记录都没有 —— 于是「用户问走势、AI 拿不到
    K 线」这件事一直没人发现，模型只能拿分时数据凑出一个"今日盘面"的回答。
    现在它会自己出现在下面「按工具看」那一节里，不需要你知道去查哪个接口。

它读的是什么
    logs/traces.jsonl（或 --trace-path 指定的文件），一次对话一行。
    其中 size / empty / error 三个字段由 services/chat_common.summarize_tool_output()
    产出 —— 加这三个字段之前的轨迹会被单独计数，不混进统计。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRACE = ROOT / "logs" / "traces.jsonl"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="轨迹汇总报告（离线，不调模型）")
    p.add_argument("--trace-path", default=str(DEFAULT_TRACE))
    p.add_argument("--limit", type=int, default=0, help="只看最近 N 条（0 表示全部）")
    p.add_argument("--engine", default=None, choices=["agents", "langchain"],
                   help="只统计某个引擎")
    p.add_argument("--tools", type=int, default=8, help="最多列几个工具")
    p.add_argument("--all-tools", action="store_true",
                   help="正常的工具也列出来（默认只列出现过空返回/错误的）")
    return p.parse_args()


def load_traces(path: Path, limit: int, engine: str | None) -> tuple:
    """逐行读 JSONL。坏行跳过并计数，不因为一行脏数据让整张表失败。"""
    records, broken = [], 0
    if not path.exists():
        return records, broken
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                broken += 1
                continue
            if engine and record.get("engine") != engine:
                continue
            records.append(record)
    if limit:
        records = records[-limit:]
    return records, broken


def percentile(values: list, ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(ratio * (len(ordered) - 1))))
    return ordered[index]


def collect(records: list) -> dict:
    stats = {
        "total": len(records),
        "legacy": 0,          # 没有 tool_results 字段（加判定之前的轨迹）
        "elapsed": [],
        "tokens": [],
        "body_chars": [],
        "empty_answer": 0,
        "truncated": 0,
        "errors": 0,
        # decided_records：有多少条轨迹**带**工具判定字段。
        # 按引擎算"平均几个工具"时分母用它，而不是用全部轨迹 —— 否则老轨迹
        # （没有 tool_results）会把平均值拉成 0，看着像"模型从不调工具"。
        "by_engine": defaultdict(
            lambda: {"count": 0, "elapsed": [], "tools": 0, "decided_records": 0}
        ),
        "tools": defaultdict(lambda: {"calls": 0, "empty": 0, "error": 0}),
        "tool_calls": 0,
        "tool_empty": 0,
        "tool_error": 0,
        "tool_undecided": 0,
        "first_ts": None,
        "last_ts": None,
    }

    for record in records:
        engine = record.get("engine", "?")
        elapsed = record.get("elapsed_ms")
        if elapsed is not None:
            stats["elapsed"].append(elapsed)
            stats["by_engine"][engine]["elapsed"].append(elapsed)
        stats["by_engine"][engine]["count"] += 1

        total_tokens = (record.get("usage") or {}).get("total_tokens")
        if total_tokens:
            stats["tokens"].append(total_tokens)

        body = record.get("body_chars")
        if body is not None:
            stats["body_chars"].append(body)
            if body < 10:
                stats["empty_answer"] += 1

        if record.get("truncated"):
            stats["truncated"] += 1
        if record.get("error"):
            stats["errors"] += 1

        ts = record.get("ts")
        if ts:
            stats["first_ts"] = min(stats["first_ts"] or ts, ts)
            stats["last_ts"] = max(stats["last_ts"] or ts, ts)

        tool_results = record.get("tool_results")
        if tool_results is None:
            stats["legacy"] += 1
            continue
        stats["by_engine"][engine]["decided_records"] += 1

        for item in tool_results:
            name = item.get("name", "unknown")
            stats["tools"][name]["calls"] += 1
            stats["tool_calls"] += 1
            stats["by_engine"][engine]["tools"] += 1
            if "empty" not in item:
                # 加判定字段之前写下的轨迹：不能默认当成"正常"，
                # 那样报表会在真有故障时显示一切健康
                stats["tool_undecided"] += 1
                continue
            if item.get("empty"):
                stats["tools"][name]["empty"] += 1
                stats["tool_empty"] += 1
            if item.get("error"):
                stats["tools"][name]["error"] += 1
                stats["tool_error"] += 1

    return stats


def _pace(values: list) -> str:
    if not values:
        return "—"
    return (f"P50 {percentile(values, 0.5) / 1000:.1f}s | "
            f"P95 {percentile(values, 0.95) / 1000:.1f}s | "
            f"最慢 {max(values) / 1000:.1f}s")


def _window(first, last) -> str:
    if not first or not last:
        return "—"
    # 同一天就只显示一次日期
    if first[:10] == last[:10]:
        return f"{first[:10]} {first[11:16]} ~ {last[11:16]}"
    # 轨迹里的 ts 是 ISO 格式（2026-09-18T22:17），把那个 T 换成空格好读一些
    return f"{first[:16].replace('T', ' ')} ~ {last[:16].replace('T', ' ')}"


def print_report(stats: dict, broken: int, trace_path: str, top_tools: int,
                 all_tools: bool) -> None:
    print()
    print("=" * 62)
    print(f"可观测性报告        轨迹: {trace_path}")
    print("-" * 62)
    print(f"对话数              {stats['total']} 条")
    if stats["first_ts"]:
        print(f"时间范围            {_window(stats['first_ts'], stats['last_ts'])}")
    print(f"延迟                {_pace(stats['elapsed'])}")

    tokens = stats["tokens"]
    if tokens:
        print(f"Token               总 {sum(tokens):,} | 平均 {sum(tokens) // len(tokens):,}/次")

    print()
    print("按引擎")
    for engine, data in sorted(stats["by_engine"].items()):
        avg = (sum(data["elapsed"]) / len(data["elapsed"]) / 1000) if data["elapsed"] else 0
        decided = data["decided_records"]
        avg_tools = data["tools"] / decided if decided else 0
        tool_note = f"平均 {avg_tools:.1f} 个工具" if decided else "无工具判定数据"
        print(f"  {engine:<11} {data['count']:>4} 条   平均 {avg:>5.1f}s   "
              f"{tool_note}")

    calls = stats["tool_calls"]
    print()
    print(f"工具调用            {calls} 次")
    if calls:
        empty_rate = stats["tool_empty"] / calls
        error_rate = stats["tool_error"] / calls
        flag = "   ← 关注" if stats["tool_empty"] else ""
        print(f"  空返回            {stats['tool_empty']} 次 ({empty_rate:.1%}){flag}")
        print(f"  错误返回          {stats['tool_error']} 次 ({error_rate:.1%})")
        if stats["tool_undecided"]:
            print(f"  未判定            {stats['tool_undecided']} 次"
                  f"（加判定字段之前的轨迹，不参与上面的比例）")

        rows = []
        for name, data in stats["tools"].items():
            if all_tools or data["empty"] or data["error"]:
                rows.append((data["empty"], data["error"], name, data))
        # 问题最多的排前面
        rows.sort(reverse=True)
        if rows:
            print("  按工具看：")
            for _, _, name, data in rows[:top_tools]:
                detail = []
                if data["empty"]:
                    detail.append(f"{data['empty']} 次为空 ({data['empty'] / data['calls']:.0%})")
                if data["error"]:
                    detail.append(f"{data['error']} 次出错")
                tail = " → " + "，".join(detail) if detail else ""
                print(f"    {name:<24} {data['calls']:>3} 次{tail}")
            if len(rows) > top_tools:
                print(f"    （还有 {len(rows) - top_tools} 个工具，用 --tools 调大）")
        elif not all_tools:
            print("  按工具看：所有工具都正常")

    print()
    print("回答")
    print(f"  空回答（正文<10字） {stats['empty_answer']} 条")
    if stats["body_chars"]:
        avg_body = sum(stats["body_chars"]) / len(stats["body_chars"])
        print(f"  平均正文           {avg_body:.0f} 字")
    if stats["truncated"]:
        print(f"  触发工具调用上限    {stats['truncated']} 条")
    if stats["errors"]:
        print(f"  执行失败            {stats['errors']} 条")
    if stats["legacy"]:
        print(f"  老轨迹（无工具判定） {stats['legacy']} 条 —— 加字段之前产生的，不参与工具统计")
    if broken:
        print(f"  坏行（JSON 解析失败）{broken} 条")


def main() -> None:
    args = parse_args()
    trace_path = Path(args.trace_path)
    records, broken = load_traces(trace_path, args.limit, args.engine)
    if not records:
        print(f"没有读到任何轨迹：{trace_path}")
        print("先跑一次对话或 python eval/run_eval.py，再回来看。")
        return
    print_report(collect(records), broken, str(trace_path), args.tools, args.all_tools)


if __name__ == "__main__":
    main()
