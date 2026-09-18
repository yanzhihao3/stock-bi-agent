"""eval/check_numbers.py 的纯函数测试。

只覆盖不依赖网络、不依赖大模型的部分：数字抽取、匹配、单条分类。
这些容差参数是根据真实轨迹调出来的（见下面几条注释），改动容易引入
假阴性比假阳性更危险 —— 所以用测试把当前行为锁住。
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# eval/ 不是包，直接按文件路径加载
_spec = importlib.util.spec_from_file_location(
    "check_numbers", ROOT / "eval" / "check_numbers.py"
)
cn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cn)


class TestExtractNumbers:
    def test_thousand_separator(self):
        assert 12345.0 in cn.extract_numbers("成交额 12,345", 20.0)

    def test_unit_wan_multiplies(self):
        # "3 万" 是数据，不能因为 3 < 门槛就被当序数词丢掉
        assert 30000.0 in cn.extract_numbers("约 3 万元", 20.0)

    def test_unit_with_space(self):
        # 中文里"31.36 亿元"这种带空格的写法很常见
        assert 3136000000.0 in cn.extract_numbers("成交额约 31.36 亿元", 20.0)

    def test_small_integer_filtered(self):
        # 序数词是主要噪音源，不该参与核对
        assert cn.extract_numbers("近三年涨了 5 次", 20.0) == []

    def test_decimal_kept_even_if_small(self):
        # 涨跌幅这类小数虽然小于门槛，但是真实数据
        assert 0.78 in cn.extract_numbers("下跌 0.78%", 20.0)

    def test_date_stripped(self):
        assert cn.extract_numbers("2026-09-18 收盘 1257.12 元", 20.0) == [1257.12]

    def test_month_day_stripped(self):
        assert cn.extract_numbers("9月18日", 20.0) == []

    def test_iso_timestamp_microseconds_stripped(self):
        # 实测：接口返回的 "2026-09-18T16:53:49.069923" 漏掉了微秒，
        # 会往对照池里塞进一个 69923
        assert cn.extract_numbers(
            '{"timestamp":"2026-09-18T16:53:49.069923"}', 20.0) == []

    def test_hex_hash_stripped(self):
        # 实测：不剥掉时间签名，回答末尾那串十六进制会被抠出 661/46/88 三个假可疑
        assert cn.extract_numbers("时间签名 2b661aa46c6aac88", 20.0) == []

    def test_stock_code_survives(self):
        # 剥哈希时不能误伤股票代码
        assert 600519.0 in cn.extract_numbers("贵州茅台 sh600519", 20.0)


class TestFindMatch:
    def test_exact(self):
        level, candidate, exponent = cn.find_match(1257.12, [1257.12, 1262.99], 0.01)
        assert level == "exact"

    def test_unit_scale(self):
        # 实测：工具返回 turnover=313585（万元），回答写"31.36 亿"
        level, candidate, exponent = cn.find_match(3.136e9, [313585.0], 0.01)
        assert level == "unit"
        assert exponent == -4

    def test_missing(self):
        level, _, _ = cn.find_match(1500.0, [1257.12, 313585.0], 0.01)
        assert level is None


class TestFmt:
    def test_stock_code_not_shown_as_wan(self):
        # 实测：600519 被写成"60.05万"后，看着像回答里凭空多出来的一个金额
        assert cn.fmt(600519) == "600519"

    def test_money_uses_yi(self):
        assert cn.fmt(3.136e9) == "31.36亿"

    def test_money_uses_wan_above_million(self):
        assert cn.fmt(1.5e7) == "1500.00万"


class TestCheckRecord:
    @staticmethod
    def _record(answer, outputs):
        return {
            "question": "测试",
            "answer": answer,
            "tool_results": [{"name": "t", "output": o} for o in outputs],
        }

    def test_all_matched(self):
        rec = self._record("最新价 1257.12 元", ['{"price":"1257.12"}'])
        assert cn.check_record(rec, 0.01, 20.0)["status"] == "ok"

    def test_fabricated_number_flagged(self):
        rec = self._record("成交量 9999 手", ['{"price":"1257.12"}'])
        result = cn.check_record(rec, 0.01, 20.0)
        assert result["status"] == "suspicious"
        assert 9999.0 in result["missing"]

    def test_unit_conversion_not_flagged(self):
        rec = self._record("成交额约 31.36 亿元", ['{"turnover":"313585"}'])
        assert cn.check_record(rec, 0.01, 20.0)["status"] == "unit_only"

    def test_restated_number_not_flagged(self):
        # 实测：先写"成交额约 31.36 亿元"、后文又说"成交 31 亿"，
        # 后者对不上工具数据，但它是同一个数字的粗略复述，不该算可疑
        rec = self._record(
            "成交额约 31.36 亿元，成交 31 亿",
            ['{"turnover":"313585"}'],
        )
        assert cn.check_record(rec, 0.01, 20.0)["status"] == "unit_only"

    def test_old_format_skipped(self):
        # 加字段之前的历史轨迹没有 tool_results / answer，不能算成可疑
        assert cn.check_record({"question": "x"}, 0.01, 20.0)["status"] == "old_format"
