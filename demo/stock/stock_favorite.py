import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# 一句话总结：类似股票软件的"自选股"功能，用户可以管理自己关注的股票列表。

# -------------------- API 配置 --------------------
BASE_URL = "http://127.0.0.1:8000"
LIST_ENDPOINT = "/v1/stock/list_fav_stock"
ADD_ENDPOINT = "/v1/stock/add_fav_stock"
DEL_ENDPOINT = "/v1/stock/del_fav_stock"
CLEAR_ENDPOINT = "/v1/stock/clear_fav_stock"

if st.session_state.get('logged', False):
    st.sidebar.markdown(f"用户名：{st.session_state['user_name']}")
# --------------------------------------------------

def _get_username():
    """获取当前用户名称，如果没有登录，则使用默认值。"""
    username = st.session_state.get('user_name')
    return username if username else None  # 未登录时不返回默认用户

# 所有API调用的"模板函数"，统一处理请求和错误。
def _call_api(endpoint: str, params: dict = None):
    """
    通用的 API 调用函数，适用于所有 POST 请求。
    (注意: 根据您的 curl 示例，所有操作都是 POST)
    """
    url = f"{BASE_URL}{endpoint}"

    try:
        # 所有收藏操作都是 POST，参数通过 URL 传递
        response = requests.post(url, params=params)
        response.raise_for_status()  # 对 4xx 或 5xx 状态码抛出异常

        data = response.json()

        if data.get("code") == 200:
            return {"success": True, "message": data.get("message"), "data": data.get("data")}
        else:
            return {"success": False, "message": data.get("message", "操作失败"), "data": None}

    except requests.exceptions.ConnectionError:
        return {"success": False, "message": f"连接错误：无法连接到后端服务 ({BASE_URL})。", "data": None}
    except requests.exceptions.HTTPError as e:
        return {"success": False, "message": f"API 请求失败：{e}。响应内容: {response.text}", "data": None}
    except Exception as e:
        return {"success": False, "message": f"发生未知错误：{e}", "data": None}


# -------------------- CRUD 业务逻辑函数 --------------------

@st.cache_data(show_spinner="正在加载收藏列表...")
def _fetch_favorites(username: str):
    """获取用户收藏的股票列表，使用缓存以避免多次查询"""
    params = {"user_name": username}
    return _call_api(LIST_ENDPOINT, params=params)


def _add_favorite(username: str, stock_code: str):
    """添加收藏股票"""
    params = {"user_name": username, "stock_code": stock_code}
    return _call_api(ADD_ENDPOINT, params=params)


def _delete_favorite(username: str, stock_code: str):
    """删除收藏股票"""
    params = {"user_name": username, "stock_code": stock_code}
    return _call_api(DEL_ENDPOINT, params=params)


def _clear_favorites(username: str):
    """清空所有收藏股票"""
    params = {"user_name": username}
    return _call_api(CLEAR_ENDPOINT, params=params)


# -------------------- Streamlit 页面 --------------------

def stock_favorite_page():
    username = _get_username()

    if not username:
        st.warning("请先登录后再管理自选股。")
        return

    st.caption(f"当前操作用户: **{username}** ")
    st.markdown("---")

    # -------------------- 1. 添加收藏股票 --------------------
    st.header("添加新的收藏")
    with st.form(key='add_fav_form'):
        new_code = st.text_input(
            "请输入股票代码",
            placeholder="例如：sh600519 或 sz002392",
        ).strip()
        add_submitted = st.form_submit_button("添加收藏")

        if add_submitted:
            if not new_code:
                st.warning("请输入有效的股票代码。")
            else:
                with st.spinner(f"正在添加 {new_code}..."):
                    result = _add_favorite(username, new_code)
                    if result['success']:
                        st.success(f"添加成功: {result['message']}")
                        _fetch_favorites.clear()  # 清除缓存
                        st.rerun()  # 刷新页面显示最新列表
                    else:
                        st.error(f"添加失败: {result['message']}")

    st.markdown("---")

    # -------------------- 2. 显示和删除收藏列表 --------------------
    st.header("我的收藏列表")

    # 加载收藏数据
    result = _fetch_favorites(username)

    if not result['success']:
        st.error(f"加载收藏列表失败: {result['message']}")
        favorites = []
    else:
        favorites = result['data']

    if not favorites:
        st.info("您的收藏列表为空。请在上方添加股票。")
    else:
        df = pd.DataFrame(favorites)

        # 统一列名和格式化时间
        if 'stock_code' in df.columns:
            df.rename(columns={'stock_code': '股票代码'}, inplace=True)
        if 'create_time' in df.columns:
            df.rename(columns={'create_time': '收藏时间'}, inplace=True)
            df['收藏时间'] = df['收藏时间'].apply(
                lambda x: datetime.fromisoformat(x.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
                if isinstance(x, str) and 'T' in x else x
            )

        st.write(f"共收藏 **{len(favorites)}** 只股票。")

        # 创建可交互的列表
        for index, row in df.iterrows():
            stock_code = row['股票代码']
            col_code, col_time, col_btn = st.columns([2, 3, 1])

            col_code.markdown(f"**{stock_code}**")
            col_time.markdown(row['收藏时间'])

            # 动态生成删除按钮
            delete_key = f"del_btn_{stock_code}_{index}"
            if col_btn.button("删除", key=delete_key, help=f"删除股票 {stock_code}"):
                with st.spinner(f"正在删除 {stock_code}..."):
                    del_result = _delete_favorite(username, stock_code)
                    if del_result['success']:
                        st.success(f"删除成功: {del_result['message']}")
                        _fetch_favorites.clear()  # 清除缓存
                        st.rerun()
                    else:
                        st.error(f"删除失败: {del_result['message']}")

    st.markdown("---")

    # -------------------- 3. 清空所有收藏 --------------------
    st.header("清空所有收藏")

    # 使用 session_state 实现二次确认逻辑
    if 'clear_confirm' not in st.session_state:
        st.session_state['clear_confirm'] = False

    st.warning("此操作将永久删除您的所有收藏股票，无法恢复。")

    if st.session_state['clear_confirm']:
        st.error("请再次点击按钮以确认清空操作！")
        if st.button("确认清空所有收藏"):
            with st.spinner("正在清空所有收藏..."):
                clear_result = _clear_favorites(username)
                if clear_result['success']:
                    st.success(f"清空成功: {clear_result['message']}")
                    st.session_state['clear_confirm'] = False
                    _fetch_favorites.clear()  # 清除缓存
                    st.rerun()
                else:
                    st.error(f"清空失败: {clear_result['message']}")
        # 添加一个取消按钮
        if st.button("取消清空操作"):
            st.session_state['clear_confirm'] = False
            st.rerun()

    elif st.button("清空所有收藏"):
        st.session_state['clear_confirm'] = True
        st.rerun()  # 触发重新运行，显示二次确认提示


if __name__ == '__main__':
    stock_favorite_page()