import streamlit as st
import requests
import pandas as pd
from typing import Optional # 类型注解，表示参数可以是None

# 一句话总结：类似股票软件的"涨跌幅排行榜"，可以根据市场、行业、涨跌幅等条件筛选排序，支持分页查看。

# -------------------- API 配置 --------------------
BASE_URL = "http://127.0.0.1:8000"
RANK_ENDPOINT = "/stock/get_stock_rank"
# --------------------------------------------------

if st.session_state.get('logged', False):
    st.sidebar.markdown(f"用户名：{st.session_state['user_name']}")

# 定义选项映射 选项映射（用户看到的 → API需要的）
NODE_OPTIONS = {
    "沪深A股 (a)": 'a', # 用户看到"沪深A股 (a)"，API需要'a'
    "上交所A股 (ash)": 'ash',
    "深交所A股 (asz)": 'asz',
    "上交所B股 (bsh)": 'bsh',
    "深交所B股 (bsz)": 'bsz',
}

SORT_OPTIONS = {
    "交易价格": 'price',
    "涨跌额": 'priceChange',
    "涨跌幅": 'changePercent',
    "成交量": 'volume',
    "成交额": 'turnover',
    "今开盘": 'open',
    "最高价": 'high',
    "最低价": 'low',
    # 更多字段可以根据需要添加...
}


# -------------------- API 调用函数 --------------------

def fetch_stock_rank(
        node: str,
        industry_code: Optional[str] = None,
        page_index: int = 1,
        page_size: int = 100,
        sort_field: str = "price",
        asc: int = 0
):
    """
    通过调用后端 API 获取股票排行数据。
    """
    url = f"{BASE_URL}{RANK_ENDPOINT}"

    params = {
        "node": node,           # 市场代码
        "pageIndex": page_index, # 页码
        "pageSize": page_size,   # 每页数量
        "sort": sort_field,      # 排序字段
        "asc": asc,              # 升序/降序
    }
    if industry_code:
        params["industryCode"] = industry_code # 行业筛选（可选）

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        if data.get("code") == 200 and data.get("data"):
            return data["data"]
        else:
            st.warning(f"API 返回成功，但数据为空或不符合预期。")
            return None

    except requests.exceptions.ConnectionError:
        st.error(f"连接错误：无法连接到后端服务 ({BASE_URL})。请确保后端服务正在运行。")
        return None
    except Exception as e:
        st.error(f"发生未知错误：{e}")
        return None


# -------------------- Streamlit 页面 --------------------

def stock_rank_page():

    # -------------------- 1. 参数选择侧边栏 --------------------
    st.sidebar.header("排行榜筛选条件")

    # 1.1 市场/板块选择 (Node)
    selected_node_name = st.selectbox(
        "选择市场/板块",
        options=list(NODE_OPTIONS.keys()),
        index=0,
        key="rank_node_select"
    )
    selected_node = NODE_OPTIONS[selected_node_name]

    # 1.2 排序字段选择 (Sort)
    selected_sort_name = st.selectbox(
        "选择排序字段",
        options=list(SORT_OPTIONS.keys()),
        index=0,
        key="rank_sort_select"
    )
    selected_sort = SORT_OPTIONS[selected_sort_name]

    # 1.3 排序方式 (Asc)
    sort_asc = st.radio(
        "排序方式",
        options=["降序 (高到低)", "升序 (低到高)"],
        index=0,
        key="rank_asc_select"
    )
    selected_asc = 1 if sort_asc == "升序 (低到高)" else 0

    # 1.4 行业代码筛选 (Industry Code)
    # 理想情况下，这里应该从 `stock_industry.py` 获取完整的行业列表
    industry_code = st.text_input(
        "行业代码筛选 (可选)",
        placeholder="例如: sw_dz (电子)",
        key="rank_industry_code",
        value="sw_sysh"
    ).strip()

    # 1.5 分页大小
    page_size = st.slider("每页显示数量", min_value=10, max_value=200, value=50, step=10)

    st.sidebar.markdown("---")

    # -------------------- 2. 主页面数据展示 --------------------
      # 分页逻辑
    # 初始化当前页码
    if 'rank_page_index' not in st.session_state:
        st.session_state['rank_page_index'] = 1

    # 按钮：触发数据加载 # 查询按钮（点击重置到第1页）
    if st.button("🔎 查询排行榜"):
        # 查询时重置页码到第一页
        st.session_state['rank_page_index'] = 1

    # 重新加载或第一次加载
    current_page = st.session_state['rank_page_index']

    # 调用 API 获取数据
    rank_data = fetch_stock_rank(
        node=selected_node,
        industry_code=industry_code if industry_code else None,
        page_index=current_page,
        page_size=page_size,
        sort_field=selected_sort,
        asc=selected_asc
    )

    if rank_data is None:
        st.stop()  # 停止执行后续代码

    # 提取核心数据
    total_records = rank_data.get('totalRecord', 0) # 总记录数
    rank_list = rank_data.get('rank', []) # 当前页数据

    # -------------------- 3. 统计和分页控件 --------------------
    # 计算总页数
    max_pages = (total_records + page_size - 1) // page_size
    # 当前显示范围
    # 例如：total=95, page_size=50 → (95+49)//50 = 144//50 = 2页
    # 显示范围
    # 第1页：1-50条
    # 第2页：51-95条
    start_record = (current_page - 1) * page_size + 1
    end_record = min(current_page * page_size, total_records)

    st.info(
        f"📈 找到 **{total_records}** 条记录。当前显示第 **{start_record}** 到 **{end_record}** 条 (第 {current_page} / {max_pages} 页)。")

    # 分页控制按钮
    col_prev, col_page_info, col_next = st.columns([1, 2, 1])

    with col_prev:
        if current_page > 1 and st.button("上一页"):
            st.session_state['rank_page_index'] -= 1
            st.rerun()

    with col_page_info:
        st.markdown(f"<p style='text-align: center; font-size: 16px;'>当前页: {current_page}</p>",
                    unsafe_allow_html=True)

    with col_next:
        if current_page < max_pages and st.button("下一页"):
            st.session_state['rank_page_index'] += 1
            st.rerun()

    st.markdown("---")

    # -------------------- 4. 排行榜数据表格 --------------------

    if rank_list:
        df_rank = pd.DataFrame(rank_list)

        # 简化和重命名列
        df_display = df_rank[[
            'code', 'name', 'price', 'priceChange', 'changePercent',
            'volume', 'turnover', 'open', 'high', 'low', 'date'
        ]].copy()

        df_display.columns = [
            '代码', '名称', '最新价', '涨跌额', '涨跌幅(%)',
            '成交量', '成交额(万)', '今开', '最高', '最低', '更新时间'
        ]

        # 应用颜色样式
        def color_rank_changes(val):
            """根据涨跌幅应用颜色"""
            if pd.isna(val):
                return ''
            try:
                # 假设涨跌幅和涨跌额都是数字或数字字符串
                val_float = float(str(val).strip('%'))
                if val_float > 0:
                    color = 'red'
                elif val_float < 0:
                    color = 'green'
                else:
                    color = 'black'
                return f'color: {color}; font-weight: bold'
            except ValueError:
                return ''

        st.dataframe(
            df_display.style.map(color_rank_changes, subset=['涨跌额', '涨跌幅(%)']),
            hide_index=True,
            width='stretch'
        )


if __name__ == '__main__':
    stock_rank_page()