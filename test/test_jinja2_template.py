"""系统提示词 Jinja2 模板单元测试（不依赖外部 API）"""

from jinja2 import Environment, FileSystemLoader


def _render_prompt(**overrides) -> str:
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("chat_start_system_prompt.jinja2")
    defaults = {
        "agent_name": "小呆助手",
        "task_description": "根据用户请求执行信息检索、内容生成或逻辑分析等任务。",
        "current_datetime": "2026-08-21 10:00:00",
        "timestamp_signature": "abc123",
    }
    defaults.update(overrides)
    return template.render(**defaults)


class TestSystemPromptTemplate:
    def test_template_renders_core_fields(self):
        prompt = _render_prompt()
        assert "小呆助手" in prompt
        assert "2026-08-21 10:00:00" in prompt
        assert "abc123" in prompt

    def test_template_has_time_signature_rule(self):
        prompt = _render_prompt()
        assert "时间签名" in prompt
        assert "禁止凭空生成时间信息" in prompt
