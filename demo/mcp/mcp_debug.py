import streamlit as st
import asyncio
import traceback
import json
from fastmcp import Client
from fastmcp.tools import Tool
from typing import List, Any
import pandas as pd

from demo.common import MCP_SERVER_URL

# 一句话总结：这是一个"工具测试台"，让你像用 Postman 一样，在网页上选择工具、填参数、看结果。

# FastMCP 服务器地址：统一由 demo/common.py 提供（环境变量可覆盖）


# --- 异步工具加载函数 (缓存结果) ---

@st.cache_data(show_spinner="正在连接 FastMCP 服务器并获取工具列表...")
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


# --- 异步工具调用函数 (实际执行调用) ---
# 大白话：用户选好工具、填好参数后，这个函数负责把请求发给 MCP 服务器，拿到结果。
def call_mcp_tool(tool_name: str, kwargs: dict) -> Any:
    """
    同步函数封装，运行异步的 client.call()。
    """

    async def execute_call():
        client = Client(MCP_SERVER_URL)
        try:
            async with client:
                # 过滤掉 None 或空字符串的参数，除非它是必填且需要传 None
                filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None and v != ''}

                # 尝试将数字字符串转换为 Python 类型
                for k, v in filtered_kwargs.items():
                    try:
                        # 如果是数字，尝试转换为 float 或 int
                        if isinstance(v, str) and (
                                v.isdigit() or (v.replace('.', '', 1).isdigit() and v.count('.') < 2)):
                            if '.' in v:
                                filtered_kwargs[k] = float(v)
                            else:
                                filtered_kwargs[k] = int(v)
                    except ValueError:
                        pass  # 保持为字符串

                st.info(f"正在调用工具 '{tool_name}'，参数: {filtered_kwargs}")

                # 执行工具调用
                result = await client.call_tool(tool_name, arguments=filtered_kwargs)
                return result

        except Exception as e:
            error_message = f"工具调用失败: {e}"
            st.error(error_message)
            traceback.print_exc()
            return {"error": error_message}

    # 在 Streamlit 的同步环境中运行异步调用
    return asyncio.run(execute_call())


# --- Streamlit 主应用逻辑 ---

def main():

    # 1. 状态和工具加载
    ping_status, all_tools = load_mcp_tools(MCP_SERVER_URL)

    if not ping_status or not all_tools:
        st.error("未能加载工具。请检查服务器是否已在 8900 端口运行，并查看上方错误详情。")
        return

    # 将工具列表转换为 {name: Tool} 字典，方便查找
    tool_map = {tool.name: tool for tool in all_tools}
    tool_names = list(tool_map.keys())

    # 2. 工具选择下拉框
    selected_tool_name = st.selectbox(
        "选择要调用的工具:",
        tool_names,
        index=0
    )

    if not selected_tool_name:
        st.warning("请选择一个工具进行调用。")
        return

    selected_tool = tool_map[selected_tool_name]

    st.markdown("---")

    # 3. 展示工具信息
    description_summary = selected_tool.description.split('**Responses:**')[0].strip()
    st.info(description_summary)

    # 4. 动态生成输入表单
    kwargs = {}

    if selected_tool.inputSchema and 'properties' in selected_tool.inputSchema:
        params = selected_tool.inputSchema['properties']
        required = selected_tool.inputSchema.get('required', [])

        # 使用 form 来收集输入，但我们只用它来组织 UI，实际调用在按钮点击后
        with st.form(key='tool_input_form'):

            # 使用列表存储参数信息，用于展示表格 大白话：把工具需要哪些参数，用表格形式展示给用户看。
            param_display_data = []

            for name, prop in params.items():
                is_required = name in required
                type_str = prop.get('type', 'Any')
                title = prop.get('title', name)
                default_val = prop.get('default', None)
                param_desc = prop.get('description', '无描述')

                # 更新展示表格数据
                param_display_data.append({
                    "参数名": name,
                    "类型": type_str,
                    "必填": "✅" if is_required else "❌",
                    "默认值": str(default_val) if default_val is not None else '无',
                    "描述": param_desc
                })

                # 动态生成输入组件
                label = f"{title} ({'必填' if is_required else '可选'})"

                # 第3部分：动态表单生成
                if type_str in ['integer', 'number']:
                    # 使用 number_input
                    kwargs[name] = st.number_input(
                        label,
                        value=default_val,
                        key=f"input_{name}",
                        step=1 if type_str == 'integer' else 0.01,
                        help=param_desc
                    ) # 数字输入框
                else:  # 默认为 string
                    # 使用 text_input
                    kwargs[name] = st.text_input(
                        label,
                        value=default_val if default_val is not None else '',
                        key=f"input_{name}",
                        help=param_desc
                    ) # 文本输入框

            # 5. 调用按钮
            submitted = st.form_submit_button("🚀 调用 FastMCP 工具")

            # 在表单下方展示参数概览表格
            st.markdown("---")
            st.caption("参数概览:")
            st.dataframe(pd.DataFrame(param_display_data), hide_index=True, width='stretch')

    else:
        submitted = st.button("🚀 调用 FastMCP 工具")
        st.info("该工具不需要输入参数。")

    # 6. 处理调用和展示结果
    if submitted:
        # 简单检查必填参数（虽然 Streamlit 组件很难做到严格的必填检查，但可以检查 None 或空字符串）
        missing_required = False
        if selected_tool.inputSchema and 'properties' in selected_tool.inputSchema:
            required_params = selected_tool.inputSchema.get('required', [])
            for name in required_params:
                if kwargs.get(name) is None or kwargs.get(name) == '':
                    st.error(f"⚠️ 缺少必填参数: **{name}**")
                    missing_required = True

        if not missing_required:
            with st.spinner(f"正在调用 {selected_tool_name}..."):
                # 执行调用
                result = call_mcp_tool(selected_tool_name, kwargs)

                st.subheader("调用结果")

                if isinstance(result, dict) and "error" in result:
                    # 错误已在 call_mcp_tool 中处理
                    pass
                else:
                    # 尝试美观地打印 JSON/数据结构
                    st.success("调用成功！")
                    try:
                        # 尝试格式化为 JSON 字符串进行展示
                        result_str = json.dumps(result, indent=4, ensure_ascii=False)
                        st.json(result_str, language='json')
                    except TypeError:
                        # 如果不是 JSON 格式，直接打印对象
                        st.write(result)


if __name__ == "__main__":
    main()
