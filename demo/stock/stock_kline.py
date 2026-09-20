import traceback

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go # 绘制K线图（蜡烛图）
from datetime import date, timedelta

from demo.common import STOCK_API_BASE_URL

# 一句话总结：类似股票软件的K线图功能，输入股票代码和时间范围，显示该股票的日K/周K/月K线图和成交量。

# -------------------- API 配置 --------------------
# --------------------------------------------------

# K线类型到API端点的映射
LINE_TYPE_MAP = {
    "日K线": "/get_day_line",
    "周K线": "/get_week_line",
    "月K线": "/get_month_line",
}

if st.session_state.get('logged', False):
    st.sidebar.markdown(f"用户名：{st.session_state['user_name']}")

def fetch_k_line_data(
        code: str,
        line_type: str,
        start_date: str,
        end_date: str,
        data_type: int = 0  # 假设 type=0 是默认的数据类型 # 复权类型（0=不复权）
):
    """
    通过调用后端 API 获取 K 线数据。
    """
    endpoint = LINE_TYPE_MAP.get(line_type)
    if not endpoint:
        st.error(f"无效的 K 线类型: {line_type}")
        return None

    url = f"{STOCK_API_BASE_URL}{endpoint}"

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
            df = df.iloc[:, :6] # 只取前6列
            df.columns=[
                "Date", "Close_Prev", "Open", "High", "Low", "Volume"
            ]

            # 转换为正确的数据类型
            df['Date'] = pd.to_datetime(df['Date']) # 日期列转为时间类型
            for col in ["Open", "High", "Low", "Close_Prev", "Volume"]:
                # 将数据类型转换为浮点数，并处理可能存在的错误值
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df.rename(columns={'Close_Prev': 'Close'}, inplace=True) # 重命名列

            return df
        else:
            st.warning(f"API 返回成功，但未找到 {code} 的 K 线数据。")
            return None

    except requests.exceptions.ConnectionError:
        st.error(f"连接错误：无法连接到后端服务 ({STOCK_API_BASE_URL})。请确保后端服务正在运行。")
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
    # 创建K线图（蜡烛图）
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
    st.plotly_chart(fig, width='stretch') # 显示K线图

    fig_volume.update_layout(
        title="成交量 Volume",
        xaxis=dict(title='日期', showticklabels=True),
        yaxis=dict(title='成交量'),
        height=200
    )
    st.plotly_chart(fig_volume, width='stretch') # 显示K线图


def stock_vis_page():
    # 默认值设置
    today = date.today()
    default_end_date = today
    default_start_date = today - timedelta(days=90)  # 默认显示最近90天
    default_code = "sh600938"

    # -------------------- 输入参数区域 --------------------
    with st.form(key='k_line_form'):

        col1, col2 = st.columns(2)
        # 输入表单
        with col1:
            stock_code = st.text_input(
                "股票代码 (Code)",
                value=default_code,
                placeholder="例如：sh600938",
                key="vis_code"
            ).strip()

            line_type = st.selectbox(
                "K 线周期类型",
                options=list(LINE_TYPE_MAP.keys()),
                key="vis_line_type"
            )

        with col2:
            start_date = st.date_input(
                "开始日期",
                value=default_start_date,
                key="vis_start_date"
            )

            end_date = st.date_input(
                "结束日期",
                value=default_end_date,
                key="vis_end_date"
            )

        submitted = st.form_submit_button("📈 绘制 K 线图")

    # -------------------- 数据获取和绘图 --------------------

    if submitted:
        if not stock_code:
            st.warning("请输入有效的股票代码。")
            return

        # 将 date 对象格式化为 API 要求的字符串
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        # 确保开始日期不晚于结束日期
        if start_date > end_date:
            st.error("开始日期不能晚于结束日期！")
            return

        with st.spinner(f"正在加载 {stock_code} 的 {line_type} 数据 ({start_date_str} 至 {end_date_str})..."):
            df_k_line = fetch_k_line_data(
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


if __name__ == '__main__':
    stock_vis_page()
