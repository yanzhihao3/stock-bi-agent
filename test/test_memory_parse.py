"""记忆提取的解析逻辑测试

锁住一件事：**"模型回了空数组（没什么可记）"和"解析失败"必须是两个结果。**

原来 `_parse_items` 有四条路径全都返回 `[]`，调用方分不出来，日志里更是
长得一模一样（都是一句 extracted 0 item(s)）—— 于是"记忆功能坏了"和
"这几句对话确实没什么可记"被混成同一件事。K 线接口那个静默故障
（HTTP 200 + data:[]）就是这么藏了很久的。
"""

from services.memory import _parse_items, _reply_head


class TestParseSuccess:
    def test_normal_add(self):
        items, error = _parse_items(
            '[{"action": "add", "key": "关注股票", "content": "用户关注贵州茅台"}]'
        )
        assert error is None
        assert items == [{"action": "add", "key": "关注股票", "content": "用户关注贵州茅台"}]

    def test_empty_array_is_success_not_failure(self):
        """模型回 [] = "这段对话没什么值得记的"，是正常结果，不是错误。"""
        items, error = _parse_items("[]")
        assert items == []
        assert error is None

    def test_json_fenced_block(self):
        items, error = _parse_items(
            '```json\n[{"action": "add", "key": "常用城市", "content": "用户在上海"}]\n```'
        )
        assert error is None
        assert len(items) == 1

    def test_extra_text_around_array(self):
        """模型多说了两句，只要 JSON 数组还在，就该解析出来。"""
        items, error = _parse_items(
            '好的，我分析了一下：\n[{"key": "关注大盘", "content": "用户常看上证指数"}]\n以上。'
        )
        assert error is None
        assert len(items) == 1

    def test_action_defaults_to_add(self):
        items, error = _parse_items('[{"key": "k", "content": "c"}]')
        assert error is None
        assert items[0]["action"] == "add"

    def test_delete_with_key_is_kept(self):
        items, error = _parse_items('[{"action": "delete", "key": "过时标签"}]')
        assert error is None
        assert items == [{"action": "delete", "key": "过时标签"}]

    def test_mixed_valid_and_invalid_keeps_valid(self):
        """只要有能用的项，就不算失败 —— 无效的那项静默跳过即可。"""
        items, error = _parse_items(
            '[{"key": "好的", "content": "内容"}, {"action": "add"}, "不是字典"]'
        )
        assert error is None
        assert len(items) == 1


class TestParseFailure:
    def test_empty_reply(self):
        items, error = _parse_items("")
        assert items == []
        assert error == "回复为空"

    def test_whitespace_only_reply(self):
        _, error = _parse_items("   \n  ")
        assert error == "回复为空"

    def test_no_array_at_all(self):
        """模型回了一段解释文字 —— 这是最需要被看见的失败。"""
        items, error = _parse_items("抱歉，我无法从这段对话中提取出值得记录的信息。")
        assert items == []
        assert error == "回复里没有 JSON 数组"

    def test_broken_json(self):
        items, error = _parse_items('[{"key": "a", "content": }]')
        assert items == []
        assert error.startswith("JSON 解析失败:")

    def test_json_object_without_array(self):
        """模型回了一个对象而不是数组 → 落进"没有 JSON 数组"这条。

        顺带记录了实现上的一个事实：切片一定以 [ 开头、] 结尾，所以
        "解析成功但顶层不是数组"是不可能出现的（那种情况会变成语法错误），
        因此代码里没有那个分支。
        """
        items, error = _parse_items('{"key": "a", "content": "b"}')
        assert items == []
        assert error == "回复里没有 JSON 数组"

    def test_all_items_missing_content(self):
        """有 items 但每一项都没有 content → 模型没按格式来，这是失败。"""
        items, error = _parse_items('[{"key": "a"}, {"key": "b"}]')
        assert items == []
        assert "格式不符" in error
        assert "2 项" in error

    def test_all_items_missing_key(self):
        items, error = _parse_items('[{"content": "有内容但没标签"}]')
        assert items == []
        assert "格式不符" in error

    def test_delete_without_key_is_failure_if_alone(self):
        """delete 缺 key 没法定位，等于什么都没做 —— 也不能当成"成功但为空"。"""
        items, error = _parse_items('[{"action": "delete"}]')
        assert items == []
        assert "格式不符" in error


class TestReplyHead:
    def test_short_reply_unchanged(self):
        assert _reply_head("嗯") == "嗯"

    def test_long_reply_truncated_with_marker(self):
        head = _reply_head("x" * 500)
        assert head.endswith("…")
        assert len(head) == 121  # 120 + 省略号

    def test_newlines_collapsed(self):
        assert "\n" not in _reply_head("第一行\n第二行")

    def test_none_safe(self):
        assert _reply_head(None) == ""
