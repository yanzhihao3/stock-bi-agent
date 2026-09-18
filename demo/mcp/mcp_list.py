import streamlit as st
import asyncio
import traceback
from fastmcp import Client
# 假设 Tool 在 fastmcp.tools 中，如用户代码所示
from fastmcp.tools import Tool
from typing import List
import pandas as pd

# 一句话总结：这是一个"工具说明书"页面，让你查看 MCP 服务器上所有工具的名称、功能描述、参数要求。
# 辅助函数：判断工具类别 (已移除，根据用户要求)


# 确保 Streamlit 应用中使用 asyncio
# st.cache_data 缓存函数结果，避免每次 Streamlit 刷新都重新连接和获取数据
@st.cache_data(show_spinner="正在连接 FastMCP 服务器并获取工具列表...")
def load_mcp_tools(url: str) -> tuple[bool, List[Tool]]:
    """
    同步函数中运行异步客户端逻辑
    """

    async def get_data():
        client = Client(url)
        try:
            async with client:
                ping_result = await client.ping() # 测试连接
                tools_list = await client.list_tools() # 获取所有工具
                return ping_result, tools_list
        except Exception as e:
            # 捕获连接失败、超时等异常
            st.error(f"连接 FastMCP 服务器失败或发生错误: {e}")
            traceback.print_exc()
            return False, []

    # 运行异步函数并返回结果
    return asyncio.run(get_data())

#大白话：每个工具用一个"折叠框"展示，点击可以展开，里面显示： 工具是做什么的（描述） 需要什么参数（参数表格）
def display_tool_info(tool: Tool):
    """
    以折叠框形式展示单个工具的详细输入参数
    """
    # 提取描述，只取到 **Responses:** 之前的部分作为摘要
    description_summary = tool.description.split('**Responses:**')[0].strip()

    # 移除了 get_tool_category 的调用，只显示工具名称
    with st.expander(f"**🔧 {tool.name}**"): # 可折叠的区域
        st.markdown(f"**功能描述:**\n\n{description_summary}")

        # 提取并展示 Query Parameters
        if tool.inputSchema and 'properties' in tool.inputSchema:
            st.markdown("---")
            st.subheader("输入参数 (Query Parameters)")

            params = tool.inputSchema['properties']
            required = tool.inputSchema.get('required', [])

            param_data = []
            for name, prop in params.items():
                is_required = name in required
                type_str = prop.get('type', 'Any')
                default_val = prop.get('default', '无')

                # 提取描述，如果存在的话
                param_desc = prop.get('description', '无描述')

                param_data.append({
                    "参数名": name,
                    "类型": type_str,
                    "必填": "✅" if is_required else "❌",
                    "默认值": str(default_val) if default_val is not None else '无',
                    "描述": param_desc
                })

            if param_data:
                # 使用 DataFrame 创建表格
                st.dataframe(pd.DataFrame(param_data), hide_index=True)
            else:
                st.info("该工具没有输入参数。")


# --- Streamlit 主应用逻辑 ---主页面布局
def main():
    MCP_SERVER_URL = "http://127.0.0.1:8900/sse"

    # 状态展示
    status_container = st.container()
    with status_container:
        st.info(f"正在尝试连接服务端: `{MCP_SERVER_URL}`")

    # 调用函数加载数据 获取工具列表
    ping_status, tools = load_mcp_tools(MCP_SERVER_URL)

    with status_container:
        if ping_status:
            st.success("✅ **客户端 Ping 成功!** 服务器连接状态良好。")
        else:
            st.error("❌ **客户端 Ping 失败!** 请检查服务器是否运行。")

    ## 工具详细列表展示
    if tools:
        # 准备用于主列表的数据
        tool_list_data = []
        for tool in tools:
            tool_list_data.append({
                "工具名称": tool.name,
                # 移除了 "类别" 字段
                "功能摘要": tool.description.split('**Responses:**')[0].strip().split('\n')[0]  # 取第一行作为摘要
            })

        # 显示工具总览表格
        st.subheader("工具总览")
        st.dataframe(pd.DataFrame(tool_list_data), hide_index=True, width='stretch')

        st.markdown("---")
        st.subheader("工具详细信息 (展开查看参数)")

        # 循环展示每个工具的详细信息
        for tool in tools:
            display_tool_info(tool)


    else:
        st.warning("未能获取到任何工具信息。请检查上面的错误信息。")


main()
