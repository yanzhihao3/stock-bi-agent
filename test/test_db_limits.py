"""数据库列长度的约束测试

起因：把业务库从 SQLite 换到 MySQL 之后，暴露出三处**只在 MySQL 上才会炸**的问题：
`chat_session.title` / `user.user_name` / `user_favorite_stock.stock_id` 都有长度限制，
但代码里从不校验。SQLite 不强制 VARCHAR 长度，所以一直没暴露；MySQL 会强制，
超长直接抛 `1406 Data too long`（500 错误）。

这个文件的两个作用：
  1. 锁住「长度常量 == 列定义」，防止以后改了一边忘了另一边；
  2. 锁住标题的截断规则（标识类字段不能截断，只能校验 —— 见 services/chat_common）
"""

from models.orm import (
    SESSION_ID_MAX,
    SESSION_TITLE_MAX,
    STOCK_ID_MAX,
    USER_NAME_MAX,
    ChatSessionTable,
    UserFavoriteStockTable,
    UserTable,
)
from services.chat_common import normalize_session_title


def _column_length(table, column: str):
    return table.__table__.c[column].type.length


class TestConstantsMatchColumns:
    """常量必须和列定义一致 —— 否则校验按 50 来、列却是 100，白校验。"""

    def test_user_name(self):
        assert _column_length(UserTable, "user_name") == USER_NAME_MAX

    def test_stock_id(self):
        assert _column_length(UserFavoriteStockTable, "stock_id") == STOCK_ID_MAX

    def test_session_id(self):
        assert _column_length(ChatSessionTable, "session_id") == SESSION_ID_MAX

    def test_session_title(self):
        assert _column_length(ChatSessionTable, "title") == SESSION_TITLE_MAX

    def test_no_string_column_is_left_without_length(self):
        """所有 String 列都必须带长度 —— 漏一个，create_all 在 MySQL 上就报
        「VARCHAR requires a length on dialect mysql」。

        这条是给以后新增列的人兜底的：忘了写长度，这个测试就红。
        """
        from sqlalchemy import String

        offenders = []
        for table in (UserTable, UserFavoriteStockTable, ChatSessionTable):
            for column in table.__table__.columns:
                if isinstance(column.type, String) and column.type.length is None:
                    offenders.append(f"{table.__tablename__}.{column.name}")
        assert offenders == [], f"这些 String 列没写长度：{offenders}"


class TestNormalizeSessionTitle:
    def test_short_title_untouched(self):
        assert normalize_session_title("你好呀") == "你好呀"

    def test_exactly_at_limit_untouched(self):
        text = "字" * SESSION_TITLE_MAX
        assert normalize_session_title(text) == text

    def test_over_limit_truncated(self):
        text = "字" * (SESSION_TITLE_MAX + 16)
        result = normalize_session_title(text)
        assert len(result) == SESSION_TITLE_MAX
        assert text.startswith(result)

    def test_empty_and_none_safe(self):
        assert normalize_session_title("") == ""
        assert normalize_session_title(None) == ""
