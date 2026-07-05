"""redis_client 单元测试（不依赖 Redis 服务）"""

from services.redis_client import _make_key, CACHE_PREFIX


class TestMakeKey:
    def test_url_only(self):
        key = _make_key("https://api.example.com/data")
        assert key == CACHE_PREFIX + "https://api.example.com/data"

    def test_with_params(self):
        key = _make_key("https://api.example.com/data", {"code": "sh600519", "type": 0})
        assert CACHE_PREFIX + "https://api.example.com/data?code=sh600519&type=0" == key

    def test_params_sorted_alphabetically(self):
        """参数按字母序排列，保证 key 确定性"""
        key1 = _make_key("https://api.example.com/data", {"b": "2", "a": "1"})
        key2 = _make_key("https://api.example.com/data", {"a": "1", "b": "2"})
        assert key1 == key2
        assert "a=1" in key1
        assert "b=2" in key1

    def test_none_params_skipped(self):
        key = _make_key("https://api.example.com/data", {"a": "1", "b": None})
        assert "b=" not in key
        assert "a=1" in key

    def test_empty_params(self):
        key = _make_key("https://api.example.com/data", {})
        key2 = _make_key("https://api.example.com/data")
        assert key == key2
