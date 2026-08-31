import re                   # 正则表达式，解析 JSON
import time                 # 时间处理
import plotly.graph_objects as go  # 画 K 线图
import requests             # HTTP 请求
import streamlit as st      # 前端框架
import asyncio              # 异步处理
import traceback            # 错误追踪
import json                 # JSON 解析
from fastmcp import Client  # MCP 客户端
from typing import List, Any
import pandas as pd         # 数据处理
from fastmcp.tools import Tool
from demo.common import API_BASE_URL, auth_headers

# 一句话总结：这是一个股票 AI 助手的前端界面，可以：与 AI 对话 调用 MCP 工具（天气、汇率等） 显示股票 K 线图

# FastMCP 服务器地址 作用：连接你之前启动的 MCP 聚合服务器（24个工具）
MCP_SERVER_URL = "http://127.0.0.1:8900/sse"

# 连接 MCP 服务器
# 获取所有可用的工具列表
# @st.cache_data 缓存结果，避免重复加载
@st.cache_data(show_spinner="正在连接 FastMCP 服务器并获取工具列表...", ttl=60)
def load_mcp_tools(url: str) -> tuple[bool, List[Tool]]:
    """
    同步函数中运行异步客户端逻辑，获取所有可用工具。
    """

    async def get_data():
        client = Client(url)
        try:
            # 使用 async with 确保客户端连接正确管理
            async with client:
                ping_result = await client.ping()
                tools_list = await client.list_tools()
                return ping_result, tools_list
        except Exception as e:
            st.error(f"连接 FastMCP 服务器失败或发生错误: {e}")
            traceback.print_exc()
            return False, []

    return asyncio.run(get_data())


# streamlit
# session_state 当前对话的缓存
# session_state.messages 此次对话的历史上下文

if st.session_state.get('logged', False):
    st.sidebar.markdown(f"用户名：{st.session_state['user_name']}")
else:
    st.info("请先登录再使用模型～")
# 4. 侧边栏 - 登录状态显示 作用：侧边栏显示当前登录用户

# 初始化对话历史
if "messages" not in st.session_state.keys():
    st.session_state.messages = []

# 有 session_id 时从后端加载历史；加载失败（未登录/token 过期/会话失效）则清掉
if st.session_state.get("session_id"):
    resp = requests.post(
        f"{API_BASE_URL}/v1/chat/get",
        params={"session_id": st.session_state["session_id"]},
        headers=auth_headers(),
    ).json()
    if resp.get("code") == 200 and resp.get("data") is not None:
        st.session_state.messages = [
            {"role": message["role"], "content": message["content"]}
            for message in resp["data"]
        ]
    else:
        st.session_state["session_id"] = None

# 6. 显示历史消息 作用：渲染所有历史消息（用户和AI），不显示 system message
if not st.session_state.messages:
    st.chat_message("assistant").write("你好！我是小呆助手，有什么可以帮你的吗？")

for message in st.session_state.messages:
    if message["role"] == "system":
        continue  # 跳过系统消息，不展示给用户
    with st.chat_message(message["role"]):
        st.write(message["content"])

# 7. 清空对话  作用：重置对话状态
def clear_chat_history():
    st.session_state.messages = []
    st.session_state.session_id = None

# 8. 侧边栏 - 工具选择  作用：侧边栏显示工具多选框，用户可以选择要启用的 MCP 工具
with st.sidebar:
    if st.session_state.get('logged', False):
        ping_status, all_tools = load_mcp_tools(MCP_SERVER_URL)

        if not ping_status or not all_tools:
            st.error("未能加载工具。请检查服务器是否已在 8900 端口运行，并查看上方错误详情。")
            selected_tool_names = []
        else:
            # 将工具列表转换为 {name: Tool} 字典，方便查找
            tool_map = {tool.name: tool for tool in all_tools}
            tool_names = list(tool_map.keys())
            # 多选框
            selected_tool_names = st.multiselect(
                "选择MCP工具:",
                options=tool_names,
            )

    # AI 引擎选择
    engine_choice = st.selectbox(
        "AI 引擎:",
        options=["agents", "langchain"],
        index=0,
        help="agents: OpenAI Agents SDK | langchain: LangChain",
    )
    st.session_state["engine"] = engine_choice

    # 对话场景（task）：可选约束，默认"自动"= 全部工具由 AI 自行判断；
    # 选具体场景会缩小工具范围（股票+天气这类混合问题建议保持自动）
    task_choice = st.selectbox(
        "对话场景:",
        options=["自动（全部工具）", "股票分析", "数据BI", "通用聊天"],
        index=0,
        help="自动时不限制工具；选具体场景会缩小可用工具范围",
    )
    st.session_state["task"] = task_choice

    st.button('清空当前聊天', on_click=clear_chat_history, width='stretch')

# 9. 请求后端聊天 API  发送消息到后端，返回 SSE 流式数据
async def request_chat(content: str, user_name: str, session_id: str) -> str:
    url = f"{API_BASE_URL}/v1/chat/"

    headers = {
        "accept": "text/event-stream",  # 修改为接受事件流
        "Content-Type": "application/json"
    }
    headers.update(auth_headers())

    data = {
        "content": content.text,
        "user_name": user_name,
        "session_id": session_id,
        "stream": True,
        "tools": selected_tool_names,
        "task": None if st.session_state.get("task") == "自动（全部工具）" else st.session_state.get("task"),
        "engine": st.session_state.get("engine", "agents"),
    }

    if not session_id:
        del data["session_id"]

    response = requests.post(url, headers=headers, json=data, stream=True)
    # 流式输出
    for content in response.iter_content(decode_unicode=True):
        if content:
            yield content

# 10. 获取新会话 ID 作用：创建新对话，获取唯一 session_id
def request_session_id():
    url = f"{API_BASE_URL}/v1/chat/init"
    headers = {
        "Content-Type": "application/json"
    }
    headers.update(auth_headers())
    response = requests.post(url, headers=headers).json()
    if response.get("code") == 200 and response.get("data"):
        return response["data"]["session_id"]
    return None

# 11. 获取 K 线数据  作用：调用后端股票 API，获取 K 线数据并转为 DataFrame
def fetch_k_line_data(
        endpoint: str,
        code: str,
        line_type: str,
        start_date: str,
        end_date: str,
        data_type: int = 0  # 假设 type=0 是默认的数据类型
):
    """
    通过调用后端 API 获取 K 线数据。
    """

    BASE_URL = "http://127.0.0.1:8000/stock/"
    url = f"{BASE_URL}{endpoint}"

    # 注意：您的 curl 示例中，日期参数被双引号包裹，但在 Python requests 中，
    # 传递日期字符串通常不需要额外的引号，后端应自行解析。
    params = {
        "code": code,
        "startDate": start_date,
        "endDate": end_date,
        "type": data_type,
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        if data.get("code") == 200 and data.get("data"):
            # 假设返回的数据结构是列表的列表：
            # [ ["日期", "昨收", "今开", "最高", "最低", "成交量"], ... ]

            # 转换为 DataFrame
            df = pd.DataFrame(data["data"])
            df = df.iloc[:, :6]
            df.columns=[
                "Date", "Close_Prev", "Open", "High", "Low", "Volume"
            ]

            # 转换为正确的数据类型
            df['Date'] = pd.to_datetime(df['Date'])
            for col in ["Open", "High", "Low", "Close_Prev", "Volume"]:
                # 将数据类型转换为浮点数，并处理可能存在的错误值
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df.rename(columns={'Close_Prev': 'Close'}, inplace=True)

            return df
        else:
            st.warning(f"API 返回成功，但未找到 {code} 的 K 线数据。")
            return None

    except requests.exceptions.ConnectionError:
        st.error(f"连接错误：无法连接到后端服务 ({BASE_URL})。请确保后端服务正在运行。")
        return None
    except Exception as e:
        st.error(f"获取 K 线数据时发生错误：{e}")
        traceback.print_exc()
        return None


def plot_candlestick(df: pd.DataFrame, code: str, line_type: str):
    """
    使用 Plotly 绘制交互式 K 线图。
    """

    # 确保数据按日期排序
    df = df.sort_values(by='Date')

    fig = go.Figure(data=[go.Candlestick(
        x=df['Date'],
        open=df['Open'],
        high=df['High'],
        low=df['Low'],
        close=df['Close'],
        name='K线'
    )])

    # 添加成交量 (Volume) 作为子图
    fig_volume = go.Figure(data=[go.Bar(
        x=df['Date'],
        y=df['Volume'],
        name='成交量'
    )])

    # 合并图表 (使用 make_subplots 可能会更好，但这里简化为两个独立的图)
    # 调整布局
    fig.update_layout(
        title=f"股票 K 线图 - {code} ({line_type})",
        xaxis_rangeslider_visible=False,  # 隐藏底部的时间轴滑动条
        xaxis=dict(title='日期'),
        yaxis=dict(title='价格'),
        hovermode="x unified",
        height=600  # 增加高度
    )

    # 绘制成交量图（如果需要合并子图，需要使用 plotly.subplots.make_subplots）
    # 在 Streamlit 中，通常将它们分开显示更简单
    st.plotly_chart(fig, width='stretch')

    fig_volume.update_layout(
        title="成交量 Volume",
        xaxis=dict(title='日期', showticklabels=True),
        yaxis=dict(title='成交量'),
        height=200
    )
    st.plotly_chart(fig_volume, width='stretch')




if prompt := st.chat_input(accept_file="multiple", file_type=["txt", "pdf", "jpg", "png", "jpeg", "doc", "docx"]):
    if not st.session_state.get('logged', False):
        st.warning("请先登录再使用对话功能。")
    elif "session_id" not in st.session_state.keys() or not st.session_state.session_id:
        new_session_id = request_session_id()
        if new_session_id:
            st.session_state.session_id = new_session_id
        else:
            st.warning("创建会话失败，请确认已登录并检查后端服务。")

    if st.session_state.get('logged', False):
        # 2. 保存用户消息
        st.session_state.messages.append({"role": "user", "content": prompt.text})
        with st.chat_message("user"):  # 用户输入
            st.markdown(prompt.text)

        # 4. 请求 AI 回复
        with st.chat_message("assistant"):  # 大模型输出
            message_placeholder = st.empty()
            placeholder = st.empty()

            with st.spinner("请求中..."):
                async def stream_output():
                    """读取 SSE 流并解析 message / error 事件，返回 (正文, 错误信息)"""
                    accumulated_text = ""
                    error_message = None
                    buffer = ""
                    try:
                        response_generator = request_chat(prompt, st.session_state['user_name'], st.session_state['session_id'])
                        async for data in response_generator:
                            buffer += data
                            # 按 SSE 帧边界（空行）切分，逐帧解析
                            while "\n\n" in buffer:
                                raw_event, buffer = buffer.split("\n\n", 1)
                                event_type = "message"
                                data_lines = []
                                for line in raw_event.splitlines():
                                    line = line.strip()
                                    if line.startswith("event:"):
                                        event_type = line[6:].strip()
                                    elif line.startswith("data:"):
                                        data_lines.append(line[5:].strip())
                                if not data_lines:
                                    continue
                                try:
                                    payload = json.loads("\n".join(data_lines))
                                except json.JSONDecodeError:
                                    continue
                                if event_type == "message":
                                    accumulated_text += payload.get("content", "")
                                    placeholder.markdown(accumulated_text + "▌")
                                elif event_type == "error":
                                    error_message = payload.get("message", "回答生成失败")
                                    break
                    except Exception as e:
                        # 连接中断等传输层异常：给用户可读提示
                        error_message = f"连接中断，请检查后端服务是否正常（{e}）"
                    return accumulated_text, error_message

                final_text, error_message = asyncio.run(stream_output())
                placeholder.markdown(final_text)  # 最终渲染一次

            if error_message:
                st.error(error_message)
            else:
                # 5. 保存 AI 回复
                st.session_state.messages.append({"role": "assistant", "content": final_text})

            if not error_message:
                try:
                    # 6. 只有真正调用了 K 线工具（day/week/month）时才绘制图表
                    first_json = re.search(r"```json\s*([\s\S]*?)\s*```", final_text, re.I)
                    if first_json:
                        raw = first_json.group(1).strip()
                        if ":" in raw:
                            tool_name = raw[:raw.index(":")].strip()
                            # operation_id -> 实际 API 路径映射
                            OPERATION_TO_PATH = {
                                "stock_get_day_line": "get_day_line",
                                "stock_get_week_line": "get_week_line",
                                "stock_get_month_line": "get_month_line",
                            }
                            if tool_name in OPERATION_TO_PATH:
                                endpoint = OPERATION_TO_PATH[tool_name]
                                argv = json.loads(raw[raw.index(":")+1:])
                                stock_code = argv.get("code", "")
                                start_date_str = argv.get("startDate", "")
                                end_date_str = argv.get("endDate", "")
                                line_type = argv.get("type", 0)
                                with st.spinner(f"正在加载 {stock_code} 数据 ({start_date_str} 至 {end_date_str})..."):
                                    df_k_line = fetch_k_line_data(
                                        endpoint=endpoint,
                                        code=stock_code,
                                        line_type=line_type,
                                        start_date=start_date_str,
                                        end_date=end_date_str
                                    )

                                    if df_k_line is not None and not df_k_line.empty:
                                        st.success(f"成功加载 {len(df_k_line)} 条数据。")
                                        plot_candlestick(df_k_line, stock_code, line_type)
                                    else:
                                        st.info("没有数据可以绘制 K 线图。请检查代码或日期范围。")
                except:
                    traceback.print_exc()
