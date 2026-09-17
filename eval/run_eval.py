#!/usr/bin/env python
"""工具选择评测跑批脚本

用法
    python eval/run_eval.py --engine agents
    python eval/run_eval.py --engine langchain --limit 3        # 只跑前 3 条，快速验证
    python eval/run_eval.py --engine agents --min-accuracy 0.8  # 低于阈值时退出码非 0（给 CI 用）

前提
    * main_mcp.py 需要在 8900 端口运行（两个引擎都通过它取工具）
    * 项目根目录要有 .env（脚本会像 main_server.py 一样加载它）

设计说明
    * 进程内直接调用 chat() 生成器，不走 HTTP —— 聊天接口需要 JWT 鉴权，
      走 HTTP 就得先造 token，徒增复杂度
    * 轨迹写到独立文件（默认 logs/eval-traces.jsonl），不混进日常对话的轨迹
    * 每条用例用独立会话；通过"本条开始前后的行号差"精确取到它产生的轨迹，
      这样带 setup 的多轮用例也不会串
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_SET = Path(__file__).resolve().parent / "golden_set.yaml"
DEFAULT_TRACE = ROOT / "logs" / "eval-traces.jsonl"
EVAL_USER = "eval_bot"
FORBID_ANY = "__any__"
MCP_HOST, MCP_PORT = "127.0.0.1", 8900


# ---------------------------------------------------------------- 参数与前置检查


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="工具选择评测")
    p.add_argument("--engine", choices=["agents", "langchain"], default="agents")
    p.add_argument("--set", dest="set_path", default=str(DEFAULT_SET))
    p.add_argument("--trace-path", default=str(DEFAULT_TRACE))
    p.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0 表示全部）")
    p.add_argument("--category", default=None,
                   help="只跑指定类别，逗号分隔，例如：--category 易混淆,闲聊（日常迭代用）")
    p.add_argument("--tag", default=None,
                   help="只跑带指定标签的用例，逗号分隔，例如：--tag 难题（快速冒烟用）")
    p.add_argument("--id", dest="ids", default=None,
                   help="只跑指定用例，逗号分隔，例如：--id stock-02,stock-03（改完重跑失败项）")
    p.add_argument("--repeat", type=int, default=1,
                   help="每个用例重复跑 N 次。边界用例本身有波动，跑一次说明不了问题，"
                        "例如：--id stock-04 --repeat 3")
    p.add_argument("--min-accuracy", type=float, default=None,
                   help="严格准确率低于该值时退出码为 1（供 CI 做门禁）")
    p.add_argument("--quiet", action="store_true", help="不打印过程，只出报告")
    return p.parse_args()


def check_mcp() -> None:
    """两个引擎都要连 MCP 服务取工具，先探一下端口，免得跑一半报一堆连接错误。"""
    with socket.socket() as s:
        s.settimeout(2)
        if s.connect_ex((MCP_HOST, MCP_PORT)) != 0:
            sys.exit(
                f"\n[中断] 连不上 MCP 服务 {MCP_HOST}:{MCP_PORT}\n"
                f"       请先在另一个终端启动：python main_mcp.py\n"
            )


def ensure_eval_user(user_name: str) -> None:
    """评测需要一个真实存在的用户。

    踩过的坑：init_chat_session() 按 user_name 查 user 表后直接取 user_id[0]，
    查不到就会以 TypeError 崩掉。所以这里做一次幂等的创建。
    """
    from models.orm import SessionLocal, UserTable

    with SessionLocal() as s:
        if s.query(UserTable).filter(UserTable.user_name == user_name).first():
            return
        s.add(UserTable(
            user_name=user_name,
            user_role="普通用户",
            password="eval-account-not-for-login",
            status=True,
        ))
        s.commit()


# ---------------------------------------------------------------- 轨迹读取


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


def read_new_traces(path: Path, from_line: int) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < from_line or not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ---------------------------------------------------------------- 判定


def judge(case: dict, tool_names: list[str]) -> dict:
    expect = set(case.get("expect_tools") or [])
    optional = set(case.get("optional_tools") or [])
    forbid = set(case.get("forbid_tools") or [])
    actual = set(tool_names)
    allowed = expect | optional

    # 多调 = 调用了不在「期望 ∪ 可选」里的工具
    unexpected = actual - allowed
    missed = sorted(expect - actual)
    extra = sorted(unexpected)

    # 违禁 = 「多调」里被 forbid 点名的那些。
    # 关键：拿 unexpected 去匹配，而不是拿 actual —— 否则 expect 与 forbid 一旦有重叠
    # （作者笔误，或用了 stock_* 这类通配符），本该调用的工具也会被判成违禁，
    # 报出一个让人摸不着头脑的失败。forbid 只该管"多调"。
    # 支持通配符：写 stock_* 表示整类股票工具，省得把 10 个工具名一个个列出来。
    if FORBID_ANY in forbid:
        violated = sorted(unexpected)
    else:
        violated = sorted(_expand(forbid, unexpected))

    if expect:
        recall = len(expect & actual) / len(expect)
    else:
        recall = 1.0 if not actual else 0.0
    precision = len(expect & actual) / len(actual) if actual else 1.0

    return {
        "strict_ok": not missed and not extra and not violated,
        "recall": recall,
        "precision": precision,
        "missed": missed,
        "extra": extra,
        "violated": violated,
        "actual": sorted(actual),
        "expect": sorted(expect),
        "optional": sorted(optional),
    }


def _expand(patterns: set[str], actual: set[str]) -> set[str]:
    """把 forbid 里的通配符模式展开成实际命中的工具名。"""
    hit: set[str] = set()
    for pattern in patterns:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            hit |= {name for name in actual if name.startswith(prefix)}
        elif pattern in actual:
            hit.add(pattern)
    return hit


# ---------------------------------------------------------------- 主流程


async def run_case(chat_fn, case: dict, trace_path: Path, verbose: bool) -> dict:
    from services.chat_common import generate_random_chat_id

    session_id = generate_random_chat_id()
    before = count_lines(trace_path)

    questions = list(case.get("setup") or []) + [case["question"]]
    if verbose:
        print(f"  会话 {session_id}  "
              + (f"[含 {len(questions) - 1} 轮前置对话] " if len(questions) > 1 else "")
              + f"提问：{case['question']}")

    for q in questions:
        gen = chat_fn(user_name=EVAL_USER, session_id=session_id,
                      task=None, content=q, tools=None)
        try:
            async for _ in gen:
                pass
        finally:
            # 显式关闭异步生成器。
            # 踩过的坑：交给 GC 去 aclose()，它的 finally 会在任意任务里执行，
            # 而 MCP 的 SSE 客户端要求「连接」和「断开」在同一个任务中完成，
            # 否则报 "Attempted to exit cancel scope in a different task"，
            # 并且会把正在进行的连接一起取消掉（langchain 引擎第 9 条就是这样崩的）。
            try:
                await gen.aclose()
            except Exception:
                pass
        # 给 MCP 连接的清理留一点时间，再进入下一条
        await asyncio.sleep(0.3)

    traces = read_new_traces(trace_path, before)
    result = judge(case, [t.get("name") for t in (traces[-1].get("tool_calls") or [])] if traces else [])
    result["id"] = case["id"]
    result["category"] = case.get("category", "未分类")
    result["question"] = case["question"]
    result["note"] = case.get("note", "")
    result["elapsed_ms"] = traces[-1].get("elapsed_ms") if traces else None
    # token 用量：两个引擎都尽力采集，采不到就留 None（不影响其它指标）
    result["usage"] = (traces[-1].get("usage") or {}) if traces else {}
    # 这轮调了几个工具。和 token 一起看，能验证"少调工具"的改进效果 ——
    # 它比"工具名对不对"更贴近真实影响：调用越多、token 越高、上下文越脏。
    result["tool_call_count"] = len(traces[-1].get("tool_calls") or []) if traces else 0
    # 回答正文长度与是否触发工具上限。这两个字段用来发现"工具选对了、但用户拿不到回答"，
    # 那类问题只看工具调用集合是完全看不出来的。
    result["body_chars"] = (traces[-1].get("body_chars") or 0) if traces else 0
    result["truncated"] = bool(traces[-1].get("truncated")) if traces else False
    result["trace_missing"] = not traces
    if traces and traces[-1].get("error"):
        result["error"] = traces[-1]["error"]
    else:
        result["error"] = None

    # 关键修正：没跑成的条目必须判为失败。
    # 否则会出现最危险的一种情况 —— 对话因连接失败而中断，tool_calls 恰好是空的，
    # 于是"闲聊类：没有调用工具"这一条被算成正确，一次彻底失败的运行报告出 100%。
    # 评测脚本最忌讳的就是把"没执行"当成"执行对了"。
    if result["trace_missing"] or result["error"]:
        result["strict_ok"] = False
        result["recall"] = 0.0
        result["precision"] = 0.0

    return result


def print_report(results: list[dict], engine: str) -> float:
    n = len(results)
    strict = sum(1 for r in results if r["strict_ok"])
    recall = sum(r["recall"] for r in results) / n
    precision = sum(r["precision"] for r in results) / n
    violated = [r for r in results if r["violated"]]
    broken = [r for r in results if r["trace_missing"] or r["error"]]

    small = [r for r in results if r["category"] == "闲聊"]
    small_ok = sum(1 for r in small if r["strict_ok"])
    elapsed = [r["elapsed_ms"] for r in results if r["elapsed_ms"]]

    print()
    print("=" * 62)
    print(f"工具选择评测    引擎: {engine}    条目: {n}")
    print("-" * 62)
    print(f"严格准确率   {strict}/{n}   {strict / n:.1%}")
    print(f"工具召回率             {recall:.1%}      （有没有漏调）")
    print(f"工具精确率             {precision:.1%}      （有没有多调）")
    print(f"违禁调用               {len(violated)} 条")
    if small:
        print(f"闲聊准确率   {small_ok}/{len(small)}   {small_ok / len(small):.1%}")
    if elapsed:
        print(f"平均耗时               {sum(elapsed) / len(elapsed) / 1000:.1f}s")
    counted = [r.get("tool_call_count") or 0 for r in results
               if not r["trace_missing"] and not r["error"]]
    if counted:
        print(f"平均工具调用数         {sum(counted) / len(counted):.1f} 个/条")
    if counted:
        avg_body = sum(r.get("body_chars") or 0 for r in results
                       if not r["trace_missing"] and not r["error"]) / len(counted)
        print(f"平均回答正文           {avg_body:.0f} 字")
    empty = [r for r in results
             if not r["trace_missing"] and not r["error"] and (r.get("body_chars") or 0) < 10]
    truncated = [r for r in results
                 if not r["trace_missing"] and not r["error"] and r.get("truncated")]
    print(f"空回答（正文<10字）     {len(empty)} 条"
          + ("   ← 用户拿不到回答" if empty else ""))
    print(f"触发工具调用上限        {len(truncated)} 条")
    total_tokens = sum((r.get("usage") or {}).get("total_tokens") or 0 for r in results)
    if total_tokens:
        print(f"累计 token             {total_tokens:,}      （成本可据此估算）")
    else:
        print("累计 token             —            （引擎未返回 usage）")
    if broken:
        print(f"无轨迹/报错            {len(broken)} 条")

    print("-" * 62)
    print("按类别")
    for cat in dict.fromkeys(r["category"] for r in results):
        rows = [r for r in results if r["category"] == cat]
        ok = sum(1 for r in rows if r["strict_ok"])
        print(f"  {cat:<8} {ok}/{len(rows)}")

    failures = [r for r in results if not r["strict_ok"]]
    if failures:
        print("-" * 62)
        print("失败明细")
        for r in failures:
            print(f"  x {r['id']}  [{r['category']}] {r['question']}")
            if r["trace_missing"]:
                print("      没有拿到轨迹记录，本条计为失败")
                continue
            if r["error"]:
                print(f"      运行时报错: {r['error']}（本条计为失败，不是工具选错）")
                continue
            print(f"      期望 {r['expect']}   实际 {r['actual']}")
            if r["missed"]:
                print(f"      漏调: {r['missed']}")
            if r["extra"]:
                print(f"      多调: {r['extra']}")
            if r["violated"]:
                print(f"      违禁调用: {r['violated']}")
            if r["note"]:
                print(f"      出题意图: {r['note']}")

    # 单独列一组：工具选对了、但回答是空的。这类问题不影响"工具选择准确率"，
    # 却直接影响用户 —— 只有把它单列出来，才不会被漂亮的总分掩盖。
    if empty:
        print("-" * 62)
        print("回答为空的用例（工具可能选对了，但用户拿不到回答）")
        for r in empty:
            print(f"  ! {r['id']}  {r['question']}")
            print(f"      工具调用 {r.get('tool_call_count', 0)} 次"
                  f"，正文 {r.get('body_chars', 0)} 字"
                  f"{'，触发了工具上限' if r.get('truncated') else ''}")
    print("=" * 62)
    return strict / n


def prepare(args: argparse.Namespace) -> tuple[Any, list[dict], Path]:
    """做完全部一次性准备工作，返回 (chat 函数, 用例列表, 轨迹路径)。

    注意这是同步函数：每条用例会用独立的事件循环执行（见 main），
    所以准备工作不能在某个循环里做。
    """
    import yaml
    from dotenv import load_dotenv

    # 先全部解析成绝对路径，再切工作目录
    trace_path = Path(args.trace_path).resolve()
    set_path = Path(args.set_path).resolve()

    # 必须在导入 services.* 之前设置：TRACE_PATH 是模块级读取环境变量的
    os.environ["TRACE_PATH"] = str(trace_path)

    # 项目里多处使用相对路径（./assert/sever.db、./assert/conversations.db），
    # 必须切到项目根目录再跑 —— 否则会在别处建出一个空数据库，
    # 评测看起来"跑通了"，结果却全是假的
    os.chdir(ROOT)

    load_dotenv(ROOT / ".env")

    cases = yaml.safe_load(set_path.read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]
    if args.category:
        wanted = {c.strip() for c in args.category.split(",") if c.strip()}
        cases = [c for c in cases if c.get("category") in wanted]
        if not cases:
            sys.exit(f"[中断] 没有匹配的类别：{args.category}")
    if args.tag:
        wanted = {t.strip() for t in args.tag.split(",") if t.strip()}
        cases = [c for c in cases if wanted & set(c.get("tags") or [])]
        if not cases:
            sys.exit(f"[中断] 没有匹配的标签：{args.tag}")
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        cases = [c for c in cases if c.get("id") in wanted]
        if not cases:
            sys.exit(f"[中断] 没有匹配的用例 id：{args.ids}")

    if args.engine == "agents":
        from services.chat import chat as chat_fn
    else:
        from services.langchain_chat import chat as chat_fn

    ensure_eval_user(EVAL_USER)
    return chat_fn, cases, trace_path


def main() -> None:
    args = parse_args()
    check_mcp()
    chat_fn, cases, trace_path = prepare(args)

    results = []
    for case in cases:
        for attempt in range(1, args.repeat + 1):
            if args.repeat > 1 and not args.quiet:
                print(f"  第 {attempt}/{args.repeat} 次")
            try:
                # 每条用例跑在独立的事件循环里。
                #
                # 踩过的坑：langchain 引擎的 MCP SSE 客户端在同一条长生命周期的循环里
                # 反复 connect/disconnect 时，会出 "Attempted to exit cancel scope in a
                # different task than it was entered in"，那个取消还会打穿到外层，
                # 把整轮评测带走。换成一条一份循环，最坏情况也只是这一条失败。
                results.append(asyncio.run(run_case(chat_fn, case, trace_path, not args.quiet)))
            except BaseException as exc:
                # 单条失败不该中断整轮评测。
                # 注意这里必须是 BaseException：Python 3.8+ 的 asyncio.CancelledError
                # 继承自 BaseException 而不是 Exception，用 except Exception 抓不到，
                # 结果就是一条崩溃把整轮评测带走（langchain 引擎实际发生过）。
                results.append({
                    "id": case.get("id", "?"), "category": case.get("category", "未分类"),
                    "question": case.get("question", ""), "note": case.get("note", ""),
                    "strict_ok": False, "recall": 0.0, "precision": 0.0,
                    "missed": [], "extra": [], "violated": [], "actual": [], "expect": [],
                    "elapsed_ms": None, "trace_missing": True, "error": f"{type(exc).__name__}: {exc}",
                })
                print(f"  ! {case.get('id')} 执行异常: {type(exc).__name__}: {exc}")

    accuracy = print_report(results, args.engine)
    if args.min_accuracy is not None and accuracy < args.min_accuracy:
        print(f"\n[门禁] 严格准确率 {accuracy:.1%} 低于阈值 {args.min_accuracy:.1%}")
        sys.exit(1)


if __name__ == "__main__":
    main()
