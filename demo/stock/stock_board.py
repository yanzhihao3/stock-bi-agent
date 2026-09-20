import streamlit as st
import requests
import pandas as pd
from datetime import datetime

from demo.common import API_BASE_URL

# 一句话总结：显示股票市场主要指数的实时价格、涨跌幅、成交量等信息，类似财经网站的大盘指数板块。

# -------------------- API 配置 --------------------
BOARD_ENDPOINT = "/stock/get_board_info" # 大盘数据接口路径

if st.session_state.get('logged', False):
    st.sidebar.markdown(f"用户名：{st.session_state['user_name']}")
# 作用：如果用户已登录，在侧边栏显示用户名
# --------------------------------------------------

# 获取大盘数据
@st.cache_data(ttl=5)  # 实时数据，设置较短的缓存时间（5秒）
def fetch_board_info():
    """
    通过调用后端 API 获取主要指数的实时信息。
    """
    url = f"{API_BASE_URL}{BOARD_ENDPOINT}"

    try:
        # 发送 GET 请求
        response = requests.get(url)
        response.raise_for_status()

        data = response.json()

        if data.get("code") == 200 and data.get("data"):
            return data["data"] # 返回指数数据列表
        else:
            st.warning(f"API 返回成功，但指数数据为空或不符合预期。")
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

# 涨跌幅颜色处理
def get_color_and_delta(change_percent_str):
    """根据涨跌幅字符串判断颜色和 Delta 文本。"""
    try:
        change_float = float(change_percent_str)
        # 涨跌幅百分比
        delta_text = f"{change_float:.2f}%"

        if change_float > 0:
            color = 'inverse'  # Streamlit metric 默认绿色代表负面，红色代表正面
        elif change_float < 0:
            color = 'normal' # 绿色（跌）
        else:
            color = 'off'  # 灰色（平）

        return color, delta_text

    except (ValueError, TypeError):
        return 'off', "N/A"

# 核心指数卡片展示
def stock_board_page():
    """定义市场看板页面的布局和逻辑"""

    # 获取指数数据
    board_info_list = fetch_board_info()

    if board_info_list is None:
        return  # 错误信息已在 fetch_board_info 中显示

    if not board_info_list:
        st.info("当前无指数数据可展示。")
        return

    # 将数据转换为 DataFrame 以便处理
    df_board = pd.DataFrame(board_info_list)

    # -------------------- 核心指数 Metric 展示 --------------------
    st.markdown("### 核心指数")

    # 将所有指数平铺展示，例如每行展示 3 个
    num_indices = len(df_board)
    cols = st.columns(min(3, num_indices))  # 创建3列

    for i, row in df_board.iterrows():
        col = cols[i % 3]
        # 提取数据
        index_name = row['name']
        current_price = row['price'] # 当前点位
        price_change = row['priceChange'] # 涨跌额
        change_percent = row['changePercent'] # 涨跌幅%

        # 确定颜色和 Delta 文本
        color_mode, delta_percent_text = get_color_and_delta(change_percent)
        # # 显示指标卡片
        with col:
            # 使用 st.metric 组件展示核心数据
            st.metric(
                label=index_name,
                value=current_price,
                delta=f"{price_change} ({delta_percent_text})",
                delta_color=color_mode  # 红色代表涨，绿色代表跌
            )

    st.markdown("---")

    # -------------------- 交易细节表格展示 --------------------
    st.markdown("### 详细交易数据")

    # 筛选并重命名列
    df_display = df_board[[
        'name', 'code', 'price', 'priceChange', 'changePercent',
        'open', 'high', 'low', 'volume', 'turnover', 'date'
    ]].copy()

    # 更好的中文列名
    df_display.columns = [
        '指数名称', '代码', '最新价', '涨跌额', '涨跌幅(%)',
        '今开', '最高', '最低', '成交量', '成交额(万)', '更新时间'
    ]

    # 格式化时间
    try:
        df_display['更新时间'] = pd.to_datetime(df_display['更新时间']).dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        pass

    # 应用颜色样式
    def color_rows(val):
        """根据涨跌幅应用颜色"""
        if pd.isna(val):
            return ''
        try:
            val_float = float(str(val).strip('%'))
            if val_float > 0:
                color = 'red'
            elif val_float < 0:
                color = 'green'
            else:
                color = 'black'
            return f'color: {color}'
        except ValueError:
            return ''

    st.dataframe(
        df_display.style.map(color_rows, subset=['涨跌额', '涨跌幅(%)']),
        hide_index=True,
        width='stretch'
    )


if __name__ == '__main__':
    stock_board_page()
