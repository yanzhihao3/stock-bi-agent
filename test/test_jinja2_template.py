from datetime import datetime

from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("templates"))
template = env.get_template("chat_start_system_prompt.jinjia2")

# 渲染
prompt = template.render(agent_name="小呆Agent", current_datetime=datetime.now())
print(prompt)