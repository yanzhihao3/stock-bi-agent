import streamlit as st
import requests
import pandas as pd

from demo.common import API_BASE_URL

# 一句话总结：类似股票软件的"搜索框"，输入"茅台"就能找到所有名称或代码包含"茅台"的股票。

# -------------------- API 配置 --------------------
SEARCH_ENDPOINT = "/stock/get_stock_code"

if st.session_state.get('logged', False):
    st.sidebar.markdown(f"用户名：{st.session_state['user_name']}")
# --------------------------------------------------

def fetch_stock_codes(keyword: str):
    """
    通过调用后端 API 获取匹配的股票代码列表。
    """
    if not keyword:
        return []

    # 完整 API URL
    url = f"{API_BASE_URL}{SEARCH_ENDPOINT}"

    # 构造请求参数
    params = {"keyword": keyword}

    try:
        # 发送 GET 请求
        response = requests.get(url, params=params)

        # 检查响应状态码
        response.raise_for_status()

        data = response.json()
        # 新版 API 返回格式：{"code": 200, "data": [{"code": "...", "name": "..."}]}
        if data.get("code") == 200 and data.get("data"):
            return data["data"]
        return []

    except requests.exceptions.ConnectionError:
        st.error(f"连接错误：无法连接到后端服务 ({API_BASE_URL})。请确保后端服务正在运行。")
        return None
    except requests.exceptions.HTTPError as e:
        st.error(f"API 请求失败：{e}")
        return None
    except Exception as e:
        st.error(f"发生未知错误：{e}")
        return None


def stock_search_page():
    """定义股票搜索页面的布局和逻辑"""

    # 使用 st.form 来组织输入和按钮
    with st.form(key='stock_search_form'):

        # 关键词输入框
        search_keyword = st.text_input(
            "请输入关键词",
            placeholder="例如：北京、腾讯控股、贵州茅台",
            key="search_input"
        )

        # 搜索按钮
        submitted = st.form_submit_button("开始搜索")

    # 只有当用户点击按钮且输入框非空时才执行搜索
    if submitted and search_keyword:

        with st.spinner(f"正在搜索包含关键词 '{search_keyword}' 的股票..."):

            # 调用函数获取数据
            results = fetch_stock_codes(search_keyword)

            if results is None:
                # 错误信息已在 fetch_stock_codes 中显示
                return

            if not results:
                st.info(f"未找到与 '{search_keyword}' 匹配的股票信息。")
            else:
                st.success(f"成功找到 {len(results)} 条结果。")

                # 将结果转换为 DataFrame 以便更好地展示
                df_results = pd.DataFrame(results)
                # 新版返回 {"code": "...", "name": "..."} 格式
                if "code" in df_results.columns and "name" in df_results.columns:
                    df_results = df_results[["code", "name"]]
                    df_results.columns = ["代码", "名称"]

                # 展示搜索结果表格
                st.dataframe(
                    df_results,
                    hide_index=True
                )

    elif submitted and not search_keyword:
        st.warning("请输入有效的搜索关键词。")


if __name__ == '__main__':
    # Streamlit 应用入口
    stock_search_page()
