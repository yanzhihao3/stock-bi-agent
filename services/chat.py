import hashlib
import os
import random
import string # 字符串工具（字母、数字字符集）
import time
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional
from functools import wraps

from agents import Agent, Runner, OpenAIChatCompletionsModel, ModelSettings
from agents.extensions.memory import AdvancedSQLiteSession  # 为 AI 提供持久化记忆，让 AI 能记住之前的对话历史。
from typing import AsyncGenerator

from agents.mcp import MCPServerSse, ToolFilterStatic # ToolFilterStati 工具过滤器，限制 AI 只能使用特定工具
from openai import AsyncOpenAI
from openai.types.responses import ResponseTextDeltaEvent, ResponseOutputItemDoneEvent, ResponseFunctionToolCall
from jinja2 import Environment, FileSystemLoader

from models.data_models import ChatSession
from models.orm import ChatSessionTable, ChatMessageTable, SessionLocal, UserTable  # 数据表
from fastapi.responses import StreamingResponse

# 用于时间签名校验的密钥，从环境变量读取，不存在则用默认值
TIMESTAMP_SECRET = os.environ.get("TIMESTAMP_SECRET", "default_secret_change_in_production")


def with_retry(max_retries: int = 3, base_delay: float = 1.0):
    """重试装饰器：捕获异常后指数退避重试，防止长尾异常导致调用失败"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)  # 指数退避: 1s, 2s, 4s
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


# 这是一个完整的AI对话后端服务，集成了MCP工具调用、对话管理、数据库存储等功能

# 工具分类定义：用于分层检索与动态激活机制
TOOL_CATEGORIES = {
    "股票分析": ["stock_get_codes", "stock_get_index_code", "stock_get_industry_code",
                "stock_get_board_info", "stock_get_rank", "stock_get_month_line",
                "stock_get_week_line", "stock_get_day_line", "stock_get_info", "stock_get_minute_data"],
    "新闻聚合": ["get_today_daily_news", "get_douyin_hot_news", "get_github_hot_news",
                "get_toutiao_hot_news", "get_sports_news"],
    "通用工具": ["get_city_weather", "get_address_detail", "get_tel_info",
                "get_flower_info", "get_rate_transform"],
    "名言鸡汤": ["get_today_familous_saying", "get_today_motivation_saying", "get_today_working_saying"],
}

# 任务类型到工具分类的映射
TASK_TO_CATEGORIES = {
    "股票分析": ["股票分析"],
    "数据BI": ["股票分析", "通用工具"],
    "通用聊天": ["名言鸡汤"],
}


def get_category_tools(category: str) -> List[str]:
    """根据分类名称获取该分类下的所有工具名"""
    return TOOL_CATEGORIES.get(category, []) # 找 "a"，找不到返回 []


def suggest_categories(task: Optional[str]) -> List[str]:
    """根据任务类型推荐工具分类"""
    if not task:
        return list(TOOL_CATEGORIES.keys())
    return TASK_TO_CATEGORIES.get(task, list(TOOL_CATEGORIES.keys()))
def generate_random_chat_id(length=12):
    with SessionLocal() as session:
        for retry_time in range(20):
            # 随机生成字符串（字母+数字）
            # 作用：生成一个包含62个字符的字符串
            characters = string.ascii_letters + string.digits # 组成：大小写字母(52) + 数字(10) = 62种可能
            session_id = ''.join(random.choice(characters) for i in range(length))
            # | 是 Python 3.10+ 的联合类型操作符，等价于 Optional[ChatSessionTable]
            # ChatSessionTable | None	类型说明：可能找到对象，也可能找不到
            chat_session_record: ChatSessionTable | None = session.query(ChatSessionTable).filter(
                ChatSessionTable.session_id == session_id).first() # 在数据库中查找指定 session_id 的会话记录，如果找到返回对象，找不到返回 None。
            if chat_session_record is None:
                break
            # 4. 如果查到了（记录已存在），说明冲突了
            # 继续循环，重新生成ID

            if retry_time > 10:
                raise Exception("Failed to generate a unique session_hash")

    return session_id

# 生成系统提示词 作用：根据任务类型（股票分析/数据BI/通用对话）生成不同的系统提示词。
def get_init_message(
        task: str,
) -> List[Dict[Any, Any]]:
    env = Environment(loader=FileSystemLoader("templates")) # 创建一个 Jinja2 环境对象，配置模板加载器 告诉 Jinja2 去 templates 文件夹查找模板文件
    template = env.get_template("chat_start_system_prompt.jinja2") # 加载并解析指定的模板文件

    if task == "股票分析":
        task_description = """
1. 专注于全球主要股票市场（如 NYSE, NASDAQ, SHSE, HKEX）的分析。
2. 必须使用专业、严谨的金融术语，如 P/E, EPS, Beta, ROI, 护城河 (Moat) 等。
3. **在提供分析时，必须清晰地说明数据来源、分析模型的局限性，并强调你的意见不构成最终的投资建议。**
4. 仅基于公开市场数据和合理的财务假设进行分析，禁止进行内幕交易或非公开信息的讨论。
5. 结果要求：提供结构化的分析（如：公司概览、财务健康度、估值模型、风险与机遇）。
"""
    elif task == "数据BI":
        task_description = """
1. 帮助用户理解他们的数据结构、商业指标和关键绩效指标 (KPI)。
2. 用户的请求通常是数据查询、指标定义或图表生成建议。
3. **关键约束：你的输出必须是可执行的代码块 (如 SQL 或 Python)，或者清晰的逻辑步骤，用于解决用户的数据问题。**
4. 严格遵守数据分析的逻辑严谨性，确保每一个结论都有数据支撑。
5. 当被要求提供可视化建议时，请推荐最合适的图表类型（如：时间序列用折线图，分类对比用柱状图）。"""
    else:
        task_description = """
1. 保持对话的自然和流畅，以轻松愉快的语气回应用户。
2. 避免过于专业或生硬的术语，除非用户明确要求。
3. 倾听用户的表达，并在适当的时候提供支持、鼓励或趣味性的知识。
4. 确保回答简洁，富有情感色彩，不要表现得像一个没有感情的机器。
5. 关键词：友好、轻松、富有同理心。
        """
    # 核心价值：通过模板引擎动态生成系统提示词，实现代码逻辑与提示词内容的分离，让不同任务模式可以复用同一个模板框架
    now = datetime.now()
    # 时间签名：用 secret 对时间做哈希，让 AI 必须引用，无法凭空生成
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    signature = hashlib.sha256((timestamp_str + TIMESTAMP_SECRET).encode()).hexdigest()[:16]
    system_prompt = template.render(
        agent_name="小呆助手",
        task_description=task_description,
        current_datetime=now.strftime("%Y-%m-%d %H:%M:%S"),
        timestamp_signature=signature,
    )
    return system_prompt

# 初始化对话会话 作用：在数据库中创建一个新的对话会话，并保存系统提示词。
def init_chat_session(
        user_name: str,
        user_question: str,
        session_id: str,
        task: str,
) -> str:

    # 创建对话的title，通过summary agent
    # 存储数据库
    with SessionLocal() as session:
        # 获取用户ID
        user_id = session.query(UserTable.id).filter(UserTable.user_name == user_name).first()
        # 创建会话记录 # 2. 创建 ChatSessionTable 对象（内存中）
        chat_session_record = ChatSessionTable(
            user_id=user_id[0], # 用户ID（从元组取第一个值）例如：user_id = (100,)  # 元组，用户ID是100
            session_id=session_id,
            title=user_question, # 用用户第一个问题作为标题
        )
        print("add ChatSessionTable", user_id[0], session_id)
        session.add(chat_session_record)
        # ？？？？SQLAlchemy 根据 chat_session_record 的类名 ChatSessionTable 知道要插入到 chat_session 表。
        # 因为 ChatSessionTable 类定义了 __tablename__ = 'chat_session'
        session.commit() # 3. 真正写入数据库（执行 INSERT）
        session.flush()

        # 创建系统消息（关联到这个会话）
        message_recod = ChatMessageTable(
            chat_id=chat_session_record.id, # 使用刚生成的自增ID
            role="system",
            content=get_init_message(task)
        )
        session.add(message_recod)
        session.flush()
        session.commit()

    return True

#  核心对话处理（最重要）用户发消息 → 保存到数据库 → AI生成回复 → 逐字返回 → 保存回复到数据库
async def chat(user_name:str, session_id: Optional[str], task: Optional[str], content: str, tools: List[str] = []):
    # 对话管理，通过session id
    # 1. 对话管理：检查会话是否存在
    if session_id:
        with SessionLocal() as session:
            record = session.query(ChatSessionTable).filter(ChatSessionTable.session_id == session_id).first()
            if not record:
                init_chat_session(user_name, content, session_id, task)

    # 将用户消息保存到数据库的函数调用
    append_message2db(session_id, "user", content)

    # 获取system message，需要传给大模型，并不能给用户展示 # 3. 获取系统提示词
    instructions = get_init_message(task)

    # agent 初始化
    external_client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )

    # mcp tools 选择 配置和连接 MCP 服务器，并选择性地过滤工具。
    # 分层检索与动态激活机制：根据任务类型自动推荐工具分类
    if not tools or len(tools) == 0:
        # 用户未指定工具时，根据任务类型自动推荐
        suggested_cats = suggest_categories(task)
        # 将推荐的分类展开为工具列表
        tools = []
        for cat in suggested_cats:
            tools.extend(get_category_tools(cat))
        tools = list(set(tools))  # 去重

    if not tools or len(tools) == 0:
        tool_mcp_tools_filter: Optional[ToolFilterStatic] = None
    else:
        tool_mcp_tools_filter: ToolFilterStatic = ToolFilterStatic(allowed_tool_names=tools)
    mcp_server = MCPServerSse(
        name="SSE Python Server",
        params={"url": "http://localhost:8900/sse"},
        cache_tools_list=False, # 是否缓存工具列表
        tool_filter=tool_mcp_tools_filter, # None = 所有工具都可以用  ToolFilterStatic(...) = 只允许列表中的工具
        client_session_timeout_seconds=20, # 客户端会话超时时间
    )

    # openai-agent支持的session存储，存储对话的历史状态 # 6. 初始化对话记忆存储
    # AdvancedSQLiteSession (当前)	Agent 记忆数据库	AI Agent 的内部对话状态、上下文向量
    session = AdvancedSQLiteSession(
        session_id=session_id, # 与 系统中的对话id 关联，存储在关系型数据库中
        db_path="./assert/conversations.db",
        create_tables=True # 自动创建表
    )

    # 如果没有选择工具，默认直接调用大模型回答 # 7. 根据是否有工具选择不同的处理方式
    if not tools or len(tools) == 0:
        agent = Agent(
            name="Assistant",
            instructions=instructions,
            # mcp_servers=[mcp_server],
            model=OpenAIChatCompletionsModel( # AI 模型配置
                model=os.environ["OPENAI_MODEL"],
                openai_client=external_client,
            ),
            # tool_use_behavior="stop_on_first_tool",
            model_settings=ModelSettings(parallel_tool_calls=False) # parallel_tool_calls=False 是告诉 AI：一次只调用一个工具，等这个工具返回结果后，再决定是否调用下一个。
        )

        result = Runner.run_streamed(agent, input=content, session=session) # 流式调用大模型
        # session=session：对话记忆存储对象（你之前创建的 AdvancedSQLiteSession）

        # 流式处理 AI 回答的核心部分，实现了逐字输出和内容保存
        assistant_message = "" # 1. 初始化空字符串，用来收集完整的回答
        async for event in result.stream_events(): # 2. 循环接收流式事件
            if event.type == "raw_response_event": # 3. 只处理原始响应事件 只关心AI说的话
                if isinstance(event.data, ResponseTextDeltaEvent): # 4. 检查这个事件是不是文字内容。
                    if event.data.delta:  # 5. 如果确实有文字内容。
                        yield f"{event.data.delta}" # 把这个字马上传给浏览器，让用户立刻看到。yield 会把数据发送到前端，让用户实时看到 AI 逐字输出。?????
                        assistant_message += event.data.delta # 7. 拼接完整回答

        # 这一条大模型回答，存储对话
        append_message2db(session_id, "assistant", assistant_message)

    # 需要调用mcp 服务进行回答
    else:
        async with mcp_server:
            # # 1. 定义需要可视化展示的工具列表
            # K线数据 = 画图用的 → 直接返回
            # 其他数据 = 需要解释的 → 让AI总结
            need_viz_tools = ["get_month_line", "get_week_line", "get_day_line", "get_stock_minute_data"]
            if set(need_viz_tools) & set(tools): # # 2. 检查用户请求的工具中是否包含这些可视化工具
                tool_use_behavior = "stop_on_first_tool" # 调用了tool，得到结果，就展示结果 # 调用工具后直接返回
            else:
                tool_use_behavior = "run_llm_again" # 调用了tool，得到结果，继续用大模型的总结结果

            # 防止 Agent 陷入无效调用死循环：限制最大工具调用次数
            MAX_TOOL_CALLS = 10
            tool_call_count = 0

            agent = Agent(
                name="Assistant",
                instructions=instructions,
                mcp_servers=[mcp_server],
                model=OpenAIChatCompletionsModel(
                    model=os.environ["OPENAI_MODEL"],
                    openai_client=external_client,
                ),
                tool_use_behavior=tool_use_behavior,
                model_settings=ModelSettings(parallel_tool_calls=False)
            )

            result = Runner.run_streamed(agent, input=content, session=session)

            assistant_message = ""
            current_tool_name = ""
            async for event in result.stream_events(): # 这段代码同时处理"AI 调用了什么工具"和"AI 说了什么话"，并把两者都发给用户看。
                # 第1部分：处理工具调用事件（已注释）
                # if event.type == "run_item_stream_event" and hasattr(event, 'name') and event.name == "tool_output" and current_tool_name not in need_viz_tools:
                #     yield event.item.raw_item["output"]
                #     assistant_message += event.item.raw_item["output"]

                # 第2段：处理工具调用事件（捕获 AI 要调什么工具）
                # 当 AI 决定调用某个工具时，捕获并显示工具名称和参数 # 第2部分：捕获工具调用的信息
                #    判断是否是原始响应事件                  确保 event 有 data 属性                 判断 data 是否是输出完成事件
                if event.type == "raw_response_event" and hasattr(event, 'data') and isinstance(event.data, ResponseOutputItemDoneEvent):
                    if isinstance(event.data.item, ResponseFunctionToolCall): # 作用：检查完成的具体内容是否是函数工具调用
                        # item：完成的具体项目  ResponseFunctionToolCall：工具调用类型
                        current_tool_name = event.data.item.name # 作用：保存被调用的工具名称
                        tool_call_count += 1

                        # 防止 Agent 陷入无效调用死循环
                        if tool_call_count >= MAX_TOOL_CALLS:
                            yield "\n[系统提示：工具调用次数已达上限，停止继续调用]\n"
                            assistant_message += "\n[系统提示：工具调用次数已达上限，停止继续调用]\n"
                            break

                        # 输出工具名和参数（JSON格式）
                        # 第1行：发送给前端  event.data.item.arguments 是AI 调用工具时传入的参数。
                        yield "\n```json\n" + event.data.item.name + ":" + event.data.item.arguments + "\n" + "```\n\n"
                        # 第2行：保存到数据库
                        assistant_message += "\n```json\n" + event.data.item.name + ":" + event.data.item.arguments + "\n" + "```\n\n"

                # 第3段：处理文本回复事件（AI 说的话）
                # run llm again 的回答： 基础tool的结果继续回答 # 处理文本回复                    判断这个事件是否包含 AI 生成的文本内容
                if event.type == "raw_response_event" and hasattr(event, 'data') and isinstance(event.data, ResponseTextDeltaEvent):
                    yield event.data.delta
                    assistant_message += event.data.delta


            append_message2db(session_id, "assistant", assistant_message)


def get_chat_sessions(session_id: str, user_name: str) -> Optional[List[Dict[str, Any]]]:
    """获取对话历史，仅限会话所有者"""
    with SessionLocal() as session:
        record: Optional[ChatSessionTable] = session.query(ChatSessionTable).filter(
            ChatSessionTable.session_id == session_id).first()
        if record is None:
            return None
        # 权限校验：必须属于当前用户
        if record.user_id is None:
            return None
        user = session.query(UserTable).filter(UserTable.id == record.user_id).first()
        if user is None or user.user_name != user_name:
            return None

        chat_messages: Optional[List[ChatMessageTable]] = session.query(ChatMessageTable) \
            .join(ChatSessionTable) \
            .filter(ChatSessionTable.session_id == session_id).all()

        result = []
        if chat_messages:
            for record in chat_messages:
                result.append({
                    "id": record.id, "create_time": record.create_time,
                    "feedback": record.feedback, "feedback_time": record.feedback_time,
                    "role": record.role, "content": record.content
                })

        return result


def delete_chat_session(session_id: str, user_name: str) -> bool:
    """删除整个对话会话及其所有消息"""
    with SessionLocal() as session:
        record: Optional[ChatSessionTable] = session.query(ChatSessionTable).filter(
            ChatSessionTable.session_id == session_id).first()
        if record is None:
            return False
        # 权限校验：必须属于当前用户
        if record.user_id is None:
            return False
        user = session.query(UserTable).filter(UserTable.id == record.user_id).first()
        if user is None or user.user_name != user_name:
            return False

        session.query(ChatMessageTable).where(ChatMessageTable.chat_id == record.id).delete()
        session.query(ChatSessionTable).where(ChatSessionTable.id == record.id).delete()
        session.commit()
        return True


def change_message_feedback(session_id: str, message_id: int, feedback: bool) -> bool:
    """对某条消息进行点赞/点踩反馈"""
    with SessionLocal() as session:
        id = session.query(ChatSessionTable.id).filter(ChatSessionTable.session_id == session_id).first()
        if id is None:
            return False

        record = session.query(ChatMessageTable).filter(ChatMessageTable.id == message_id,
                                                        ChatMessageTable.chat_id == id[0]).first()
        if record is not None:
            record.feedback = feedback
            record.feedback_time = datetime.now()
            # 是的！更新操作不需要 add()，直接修改对象后 commit() 就行。
            session.commit()

        return True


def list_chat(user_name: str) -> Optional[List[Any]]:
    """列出用户的所有对话会话"""
    with SessionLocal() as session:
        # 1. 根据用户名查询用户ID
        user_id = session.query(UserTable.id).filter(UserTable.user_name == user_name).first()
        if user_id: # 2. 如果用户存在，查询该用户的所有会话
            # 作用：告诉数据库要查 chat_session 表，但只取这4个字段，不要全部字段。
            # .all()作用：执行查询，返回所有匹配的记录（返回列表，没有就是空列表 []）
            chat_records: Optional[List[ChatSessionTable]] = session.query(
                                         ChatSessionTable.user_id,
                                         ChatSessionTable.session_id,
                                         ChatSessionTable.title,
                                         ChatSessionTable.start_time).filter(ChatSessionTable.user_id == user_id[0]).all()
            if chat_records: # 3. 转换为对象列表返回
                return [ChatSession(user_id = x.user_id, session_id=x.session_id, title=x.title, start_time=x.start_time) for x in chat_records]
            else:
                return []
        else:
            return []


def append_message2db(session_id: str, role: str, content: str) -> bool:
    """添加一条消息到数据库"""
    with SessionLocal() as session:
        chat_record = session.query(ChatSessionTable.id).filter(ChatSessionTable.session_id == session_id).first()
        if chat_record:
            message_record = ChatMessageTable(
                chat_id=chat_record[0],
                role=role,
                content=content
            )
            session.add(message_record)
            session.commit()