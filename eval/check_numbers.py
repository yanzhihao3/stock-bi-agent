#!/usr/bin/env python
"""回答数字一致性核对 —— 离线跑，不调用任何大模型

用法
    python eval/check_numbers.py                                  # 扫 logs/traces.jsonl
    python eval/check_numbers.py --trace-path logs/eval-traces.jsonl
    python eval/check_numbers.py --show 10 --tolerance 0.02
    python eval/check_numbers.py --limit 1 --dump                 # 摊开看最近一条

它在做什么
    拿「工具返回里的数字」当标准答案，去核对「模型回答正文里的数字」。
    两边都只是本地的字符串 / 数值处理，**不消耗任何 token**。

    这是工具选择评测的补充：那边量的是"模型有没有选对工具"（过程指标），
    这边量的是"模型有没有说错数字"（结果指标）。

前提
    trace 里要有 tool_results（工具返回）和 answer（完整回答）两个字段。
    两个引擎现在都在写；更早的历史轨迹没有这两个字段，会被自动跳过并计数。

怎么判读（很重要）
    输出的是**可疑清单**，不是对错判定。下面几种情况都会误报，
    人工扫的时候要能分辨，别急着改代码：

      * 模型自己算出来的数字 —— 比如拿收盘价和涨跌额算出涨跌幅，那个数本来
        就不在工具返回里。这是最常见的误报来源。
      * 单位换算 —— 工具返回"万元"、回答写"亿元"（实测：turnover=313585
        对应回答里的"31.36 亿"）。这类会被单独归到"疑似单位换算"，不进可疑清单，
        因为它多半是模型做对了换算。但也不直接判为正确：只做 10 的整数次幂这一步，
        真出现量级错误仍留在可疑里。
      * 小数/百分比口径 —— 工具返回 0.0075、回答写"0.75%"，这种差异**没有**做
        模糊匹配。刻意不做：真去 ×100 猜，会把真实的量级错误一起盖掉。
      * 工具返回被截断 —— 条目上会标 [截断]，说明"找不到依据"可能只是那一段
        正好落在截断之外（K 线类工具返回很长，优先看这种）。
      * 小数字被门槛挡掉 —— 默认只保留"≥20 或带小数点"的数字。"涨 1%"里的 1、
        "近三年"里的 3 不参与核对（它们本来也是噪音），但气温 29、湿度 26
        这类真实数据会保留。再往下调 --min-value 就会把序数词混进来。

    所以正确用法是：脚本挑可疑 → 人工看一眼 → 是误报就调规则，
    是真错就把它固化成 eval/golden_set.yaml 里的一条新用例。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_TRACE = ROOT / "logs" / "traces.jsonl"

# 数字后面可能跟的单位。只覆盖股票 / 汇率 / 新闻场景里常见的几个。
_UNIT_FACTOR = {"百": 100.0, "千": 1_000.0, "万": 10_000.0, "亿": 100_000_000.0}

# 先剥掉那些"是数字但不是数据"的东西，否则日期时间会刷满可疑清单
_STRIP_PATTERNS = (
    re.compile(r"\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?"),  # 2026-09-18 / 2026年9月18日
    re.compile(r"\d{4}\s*[-/]\s*\d{1,2}"),                              # 2026-09
    re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日"),                          # 9月18日（不带年份）
    # 15:27 / 15:27:33 / 16:53:49.069923 —— 末尾的微秒不带上就会漏出 069923 这种假数字
    re.compile(r"\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2}(?:\.\d+)?)?"),
    # 哈希/ID 串：实测回答末尾的"时间签名 2b661aa46c6aac88"会被抠出 661/46/88
    # 这类纯噪音。限制成"至少 12 位连续十六进制字符、且至少含一个 a-f 字母"，
    # 这样股票代码（sh600519 里最长的一串十六进制字符只有 6 位）和长数字都不受影响。
    re.compile(r"(?=[0-9a-f]*[a-f])[0-9a-f]{12,}"),
    # URL：实测天气工具返回里带图片地址 .../wsymbols01_png_64，会往"标准答案"里
    # 塞进一个 64。池子是拿来做对照基准的，掺噪音只会增加误判成"对得上"的机会。
    re.compile(r"https?://\S+"),
)

# 数字本体：允许千分位和小数点
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# 真出现量级差异时，多半是"工具返回万元、回答写亿元"这类换算，而不是模型编造。
# 只认 10 的整数次幂；差得没规律的一律留在可疑清单里。
_POWER_LEVELS = (4, 3, 2, -2, -3, -4)

# 模型常把同一个数字换个精度复述一遍：实测同一条回答里先写"成交额约 31.36 亿元"、
# 后文又说"成交 31 亿"。前者能对上工具数据、后者对不上，但它们说的是同一件事。
# 某个数找不到依据、却和另一个"已经对上"的数字相差在 3% 以内时，按复述处理。
#
# 注意：这个判断**不能**并进上面的量级比较里 —— 试过把量级容差放宽到 5%，
# 结果回答里的 1500 被匹配成"某个成交额 10^4 倍之后的近似值"，
# 一条真可疑的数字反而被漏掉了。宽松匹配会制造假阴性，比误报更危险。
_RESTATE_TOLERANCE = 0.03


def strip_non_data_numbers(text: str) -> str:
    """把日期、时间这类格式化数字替换掉。"""
    for pattern in _STRIP_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def extract_numbers(text: str, min_value: float) -> list:
    """抽出文本里"像数据"的数字（带单位换算）。

    过滤规则：绝对值小于 min_value **且** 不含小数点的一律丢掉 ——
    "近三年""前 5 名""1 个工具"这类序数词会被整批滤掉，
    而 0.75（涨跌幅）、12.5（涨跌额）这种带小数的会保留。
    带单位的（3 万）先换算再判断，所以不会被这个门槛误伤。
    """
    text = strip_non_data_numbers(text or "")
    found = []
    for match in _NUM_RE.finditer(text):
        raw = match.group(0)
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        # 跳过空格再看紧跟的一个字：中文里"31.36 亿元"这种带空格的写法很常见
        factor = _UNIT_FACTOR.get(text[match.end():].lstrip()[:1])
        if factor:
            value *= factor
        elif "." not in raw and abs(value) < min_value:
            continue
        found.append(value)
    return found


def _close(a: float, b: float, tolerance: float) -> bool:
    """相对容差比较，容忍四舍五入。"""
    return abs(a - b) <= tolerance * max(abs(a), abs(b))


def find_match(value: float, pool: list, tolerance: float) -> tuple:
    """在 pool 里找 value 的依据，返回 (level, candidate, exponent)。

    level 取值：
      'exact' —— 直接对上
      'unit'  —— 差 10 的整数次幂，疑似单位换算
      None    —— 完全找不到依据
    """
    for candidate in pool:
        if _close(value, candidate, tolerance):
            return "exact", candidate, 0
    for exponent in _POWER_LEVELS:
        scaled = value * (10.0 ** exponent)
        for candidate in pool:
            if _close(scaled, candidate, tolerance):
                return "unit", candidate, exponent
    return None, None, 0


def fmt(value: float) -> str:
    """把大数字写成"亿/万"，否则报表明细全是 3.136e+09 这种没法读的东西。

    门槛刻意定得比 1 万高：股票代码是 6 位数（600519），用"万"格式会写成
    "60.05 万"，看上去像个金额 —— 实测这条差点被当成"回答里多出来的数字"。
    门槛取 10^6 之后，代码/量（六位以内）按原样显示，金额才走 万/亿。
    """
    if abs(value) >= 1e8:
        return f"{value / 1e8:.2f}亿"
    if abs(value) >= 1e6:
        return f"{value / 1e4:.2f}万"
    return f"{value:g}"


def was_truncated(tool_results: list) -> bool:
    """工具返回里有没有被截断的（截断标记由 truncate_for_trace 写入）。"""
    return any("已截断" in (item.get("output") or "") for item in tool_results)


def answer_body(text: str) -> str:
    """复用 chat_common 的正文剥离逻辑，保证和评测统计口径完全一致。

    放在函数里 import 是因为 services.chat_common 在导入时就要校验
    TIMESTAMP_SECRET —— 必须在 load_dotenv() 之后才能导入。
    """
    from services.chat_common import answer_body as impl
    return impl(text)


def check_record(record: dict, tolerance: float, min_value: float) -> dict:
    """核对单条轨迹。返回带 status 的字典，status 取值见下面注释。"""
    tool_results = record.get("tool_results")
    answer = record.get("answer")

    # 加字段之前的老轨迹：不参与统计，单独计数（否则会显得"可疑"暴增）
    if tool_results is None or answer is None:
        return {"status": "old_format"}

    pool = []
    for item in tool_results:
        pool.extend(extract_numbers(item.get("output") or "", min_value))

    claimed = extract_numbers(answer_body(answer), min_value)

    # 没调工具（闲聊）或没提到数字：没有可对照的东西，不算可疑
    if not pool or not claimed:
        return {"status": "not_comparable"}

    missing, unit_only, restated = [], [], []
    matched = []  # 已经对上工具数据的值，用来识别"同一数字换个精度复述"
    for value in dict.fromkeys(claimed):
        level, candidate, exponent = find_match(value, pool, tolerance)
        if level == "exact":
            matched.append(value)
            continue
        if level == "unit":
            unit_only.append((value, candidate, exponent))
            matched.append(value)
            continue
        twin = next((m for m in matched if _close(value, m, _RESTATE_TOLERANCE)), None)
        if twin is not None:
            restated.append((value, twin))
            continue
        missing.append(value)

    if missing:
        status = "suspicious"
    elif unit_only or restated:
        status = "unit_only"
    else:
        status = "ok"
    return {
        "status": status,
        "missing": missing,
        "unit_only": unit_only,
        "restated": restated,
        "tool_names": [item.get("name", "unknown") for item in tool_results],
        "truncated": was_truncated(tool_results),
        "body": answer_body(answer),
    }


def load_traces(path: Path, limit: int) -> tuple:
    """逐行读 JSONL。坏行跳过并计数，不因为一行脏数据整批失败。"""
    records, broken = [], 0
    if not path.exists():
        return records, broken
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                broken += 1
    if limit:
        records = records[-limit:]  # 只看最近 N 条
    return records, broken


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="回答数字一致性核对（离线，不调模型）")
    p.add_argument("--trace-path", default=str(DEFAULT_TRACE),
                   help="轨迹文件；跑过评测的话是 logs/eval-traces.jsonl")
    p.add_argument("--limit", type=int, default=0, help="只看最近 N 条（0 表示全部）")
    p.add_argument("--show", type=int, default=20, help="最多列几条可疑明细")
    p.add_argument("--show-units", action="store_true",
                   help="额外列出「只差单位换算/复述」的条目（默认只看数量）")
    p.add_argument("--dump", action="store_true",
                   help="摊开看最近一条：调了什么工具、两边各抽到哪些数字、回答正文")
    p.add_argument("--tolerance", type=float, default=0.01,
                   help="相对容差，默认 1%%，用来容忍四舍五入")
    p.add_argument("--min-value", type=float, default=20.0,
                   help="小于这个值且不带小数点的数字视为序数词，忽略（默认 20，"
                        "能覆盖气温/湿度这类小数值；调大可以滤掉更多噪音）")
    return p.parse_args()


def print_report(results: list, broken: int, trace_path: str, show: int,
                 show_units: bool = False) -> None:
    total = len(results)

    def count(status: str) -> int:
        return sum(1 for r in results if r["status"] == status)

    comparable = count("ok") + count("unit_only") + count("suspicious")
    suspicious = [r for r in results if r["status"] == "suspicious"]

    print()
    print("=" * 62)
    print(f"回答数字一致性核对    轨迹: {trace_path}")
    print("-" * 62)
    print(f"读取记录               {total} 条")
    print(f"可核对（有工具返回+有回答）  {comparable} 条")
    print(f"数字全部直接对得上      {count('ok')} 条")
    print(f"只差单位换算/复述       {count('unit_only')} 条   （也算通过）")
    print(f"可疑                   {count('suspicious')} 条"
          + ("   ← 需要人工看一眼" if suspicious else ""))
    print(f"无可比数字（闲聊等）    {count('not_comparable')} 条")
    print(f"老轨迹（无新字段）      {count('old_format')} 条")
    if broken:
        print(f"坏行（JSON 解析失败）   {broken} 条")

    if not suspicious:
        print("\n没有可疑条目。")
        if show_units:
            _print_unit_details(results, show)
        return

    print()
    print("可疑明细")
    print("-" * 62)
    # 被截断的排前面：它的"找不到依据"最可能是假警报，先看清楚
    suspicious.sort(key=lambda r: not r["truncated"])
    for r in suspicious[:show]:
        flag = " [截断]" if r["truncated"] else ""
        print(f"x {r['question']}{flag}")
        print(f"  调用的工具: {', '.join(r['tool_names'])}")
        print(f"  回答里找不到依据的数字: {', '.join(fmt(v) for v in r['missing'])}")
        if r["unit_only"]:
            pairs = ", ".join(
                f"{fmt(v)}（工具值 {fmt(c)}，差 10^{e}）" for v, c, e in r["unit_only"]
            )
            print(f"  疑似单位换算（通常不是错）: {pairs}")
        if r["restated"]:
            pairs = ", ".join(f"{fmt(v)}（近似已对上的 {fmt(m)}）" for v, m in r["restated"])
            print(f"  同一数字的粗略复述: {pairs}")
        snippet = r["body"].replace("\n", " ")[:110]
        print(f"  正文片段: {snippet}{'...' if len(r['body']) > 110 else ''}")
        print()
    if len(suspicious) > show:
        print(f"（还有 {len(suspicious) - show} 条未列出，用 --show 调大）")

    print("-" * 62)
    print("提醒：这是可疑清单不是判定结果。模型自己算出来的数字、单位口径差异")
    print("      都会误报。人工确认后再决定是调规则还是固化成评测用例。")

    if show_units:
        _print_unit_details(results, show)


def _print_unit_details(results: list, show: int) -> None:
    """列出"只差单位换算 / 只是复述"的条目，用于确认它们确实无害。"""
    items = [r for r in results if r["status"] == "unit_only"]
    if not items:
        return
    print()
    print("单位换算 / 复述明细（默认不列，用 --show-units 打开）")
    print("-" * 62)
    for r in items[:show]:
        parts = []
        if r["unit_only"]:
            parts.append("单位换算: " + ", ".join(
                f"{fmt(v)} ↔ {fmt(c)}（10^{e}）" for v, c, e in r["unit_only"]))
        if r["restated"]:
            parts.append("复述: " + ", ".join(
                f"{fmt(v)} ≈ {fmt(m)}" for v, m in r["restated"]))
        print(f"- {r['question']}")
        for part in parts:
            print(f"    {part}")


def main() -> None:
    args = parse_args()

    # 和 run_eval.py 一样：先加载 .env，再 import 项目模块
    # （chat_common 在导入时就会校验 TIMESTAMP_SECRET，缺了会直接报错）
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    trace_path = Path(args.trace_path)
    records, broken = load_traces(trace_path, args.limit)
    if not records:
        print(f"没有读到任何轨迹：{trace_path}")
        print("先跑一次对话或 python eval/run_eval.py，再回来核对。")
        return

    results = []
    for record in records:
        checked = check_record(record, args.tolerance, args.min_value)
        checked["question"] = record.get("question", "?")
        checked["engine"] = record.get("engine", "?")
        results.append(checked)

    if args.dump:
        dump_record(records[-1], args.min_value)

    print_report(results, broken, str(trace_path), args.show, args.show_units)


def dump_record(record: dict, min_value: float) -> None:
    """把一条轨迹摊开：调了什么工具、工具返回里抽到哪些数字、回答正文说了什么。

    用途是自测"刚问的这一条到底发生了什么" —— 干净的回答在报告里不会显示任何明细，
    光看汇总没法确认它到底有没有被核对到。
    """
    print()
    print("=" * 62)
    print("轨迹详情（最近一条）")
    print("-" * 62)
    print(f"引擎     : {record.get('engine')}")
    print(f"问题     : {record.get('question')}")
    calls = [t.get("name", "?") for t in record.get("tool_calls") or []]
    print(f"工具调用 : {', '.join(calls) if calls else '（无）'}")

    results = record.get("tool_results")
    if results is None:
        print("轨迹字段 : 缺 tool_results / answer（这条是加字段之前的旧轨迹）")
        return

    print()
    print("工具返回里抽到的数字:")
    if not results:
        print("  （无工具返回）")
    for item in results:
        numbers = list(dict.fromkeys(
            extract_numbers(item.get("output") or "", min_value)))
        preview = ", ".join(fmt(v) for v in numbers[:14])
        more = f" …共 {len(numbers)} 个" if len(numbers) > 14 else ""
        print(f"  [{item.get('name', '?')}] {preview or '（没有像数据的数字）'}{more}")

    body = answer_body(record.get("answer") or "")
    print()
    print("回答正文:")
    print("  " + (body.replace("\n", "\n  ") if body else "（空）"))

    claimed = list(dict.fromkeys(extract_numbers(body, min_value)))
    print()
    print("回答里抽到的数字:")
    print("  " + (", ".join(fmt(v) for v in claimed) if claimed else "（没有像数据的数字）"))


if __name__ == "__main__":
    main()
