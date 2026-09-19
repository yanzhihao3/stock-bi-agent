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
    p.add_argument("--recent", type=int, default=0,
                   help="再列最近 N 条对话：问了什么、调了哪些工具、哪个返回是空的。"
                        "多问几句之后用这个一眼看出哪条出问题")
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
        "tools": defaultdict(lambda: {"calls": 0, "empty": 0, "error": 0, "undecided": 0}),
        "tool_calls": 0,
        "tool_empty": 0,
        "tool_error": 0,
        "tool_undecided": 0,
        # 有多少条对话**至少**碰到一次工具空/错。工具级比例看的是接口健康度，
        # 这个看的是用户实际感受到几次 —— 一次对话里连调三次全空，对用户来说是
        # 一次糟糕体验，不是三次。
        "affected_records": 0,
        "decided_records": 0,
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

        hit = False
        for item in tool_results:
            name = item.get("name", "unknown")
            stats["tools"][name]["calls"] += 1
            stats["tool_calls"] += 1
            stats["by_engine"][engine]["tools"] += 1
            if "empty" not in item:
                # 加判定字段之前写下的轨迹：不能默认当成"正常"，
                # 那样报表会在真有故障时显示一切健康
                stats["tools"][name]["undecided"] += 1
                stats["tool_undecided"] += 1
                continue
            if item.get("empty"):
                stats["tools"][name]["empty"] += 1
                stats["tool_empty"] += 1
                hit = True
            if item.get("error"):
                stats["tools"][name]["error"] += 1
                stats["tool_error"] += 1
                hit = True
        if hit:
            stats["affected_records"] += 1
        stats["decided_records"] += 1

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
    undecided = stats["tool_undecided"]
    decided_calls = calls - undecided
    suffix = f"（可判定 {decided_calls} 次，未判定 {undecided} 次）" if undecided else ""
    print(f"工具调用            {calls} 次{suffix}")
    if decided_calls:
        # 分母只能用"可判定"的次数：加判定字段之前的调用既不能算健康、
        # 也不能算故障，放进分母会把空返回率算小（实测 4/10 会被算成 4/13）
        empty_rate = stats["tool_empty"] / decided_calls
        error_rate = stats["tool_error"] / decided_calls
        flag = "   ← 关注" if stats["tool_empty"] else ""
        print(f"  空返回            {stats['tool_empty']} 次 ({empty_rate:.1%}){flag}")
        print(f"  错误返回          {stats['tool_error']} 次 ({error_rate:.1%})")
        if stats["decided_records"]:
            affected = stats["affected_records"]
            rate = affected / stats["decided_records"]
            print(f"  受影响的对话       {affected} 条 ({rate:.1%})"
                  f"   ← 用户实际感受到多少次")

        rows = []
        for name, data in stats["tools"].items():
            if all_tools or data["empty"] or data["error"]:
                rows.append((data["empty"], data["error"], name, data))
        # 问题最多的排前面
        rows.sort(reverse=True)
        if rows:
            print("  按工具看：")
            for _, _, name, data in rows[:top_tools]:
                judged = data["calls"] - data["undecided"]
                detail = []
                if data["empty"]:
                    detail.append(f"{data['empty']} 次为空 ({data['empty'] / judged:.0%})")
                if data["error"]:
                    detail.append(f"{data['error']} 次出错")
                tail = " → " + "，".join(detail) if detail else ""
                print(f"    {name:<24} {judged:>3} 次{tail}")
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


def _tools_desc(record: dict) -> str:
    """一条对话里的工具调用摘要，空的/错的直接标出来。"""
    tools = record.get("tool_results")
    if tools is None:
        return "（老轨迹，没有工具判定字段）"
    if not tools:
        return "未调用工具"
    parts = []
    for item in tools:
        name = item.get("name", "?")
        if item.get("empty"):
            parts.append(f"{name}[空]")
        elif item.get("error"):
            parts.append(f"{name}[错]")
        else:
            parts.append(name)
    return ", ".join(parts)


def print_recent(records: list, limit: int) -> None:
    """最近 N 条对话的横向对照。

    汇总数字适合看趋势，但"我刚问的这几句到底哪条出问题了"要看这个 ——
    中文和英文宽度不一致，硬对齐反而难看，所以每条占两行。
    """
    if limit <= 0:
        return
    rows = [r for r in records if r.get("question")][-limit:]
    if not rows:
        return

    print()
    print(f"最近 {len(rows)} 条对话")
    print("-" * 62)
    for index, record in enumerate(reversed(rows), start=1):
        elapsed = record.get("elapsed_ms")
        body = record.get("body_chars")
        extra = []
        if elapsed is not None:
            extra.append(f"{elapsed / 1000:.1f}s")
        if body is not None:
            extra.append(f"正文 {body} 字")
        if record.get("error"):
            extra.append("执行失败")
        print(f"  [{index}] {record.get('question', '?')}")
        # session_id 留着是为了能直接 grep 日志，和 traces.jsonl 里的名字一致
        print(f"      {record.get('engine', '?')} | {record.get('session_id', '?')}"
              f" | {_tools_desc(record)}"
              + (f" | {' / '.join(extra)}" if extra else ""))


def main() -> None:
    args = parse_args()
    trace_path = Path(args.trace_path)
    records, broken = load_traces(trace_path, args.limit, args.engine)
    if not records:
        print(f"没有读到任何轨迹：{trace_path}")
        print("先跑一次对话或 python eval/run_eval.py，再回来看。")
        return
    print_report(collect(records), broken, str(trace_path), args.tools, args.all_tools)
    print_recent(records, args.recent)


if __name__ == "__main__":
    main()
