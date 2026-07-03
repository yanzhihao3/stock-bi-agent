import streamlit as st
import requests
import pandas as pd
import plotly.express as px # 绘制分时图（比plotly.graph_objects更简单）
from datetime import datetime

# 一句话总结：类似股票软件的"分时图"功能，显示股票当天的实时价格走势和每分钟成交量。

# -------------------- API 配置 --------------------
BASE_URL = "http://127.0.0.1:8000/stock"
MINUTE_DATA_ENDPOINT = "/get_stock_minute_data"

if st.session_state.get('logged', False):
    st.sidebar.markdown(f"用户名：{st.session_state['user_name']}")

# --------------------------------------------------


def fetch_minute_data(code: str):
    """
    通过调用后端 API 获取股票的分时数据和实时行情。
    """
    if not code:
        return None, None

    url = f"{BASE_URL}{MINUTE_DATA_ENDPOINT}"
    params = {"code": code}

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        if data.get("code") == 200 and data.get("data"):
            full_data = data["data"]
            if isinstance(full_data, dict):
                min_data = full_data.pop("minData", [])
                realtime_info = {k: v for k, v in full_data.items() if k != "minData"}
            else:
                min_data = []
                realtime_info = full_data
            return realtime_info, min_data
        else:
            st.warning(f"API 返回成功，但未找到代码 {code} 的分时数据。")
            return None, None

    except requests.exceptions.ConnectionError:
        st.error(f"连接错误：无法连接到后端服务 ({BASE_URL})。请确保后端服务正在运行。")
        return None, None
    except Exception as e:
        st.error(f"获取分时数据时发生错误：{e}")
        return None, None


def get_color_and_delta(change_percent_str):
    """根据涨跌幅字符串判断颜色和 Delta 文本。"""
    try:
        change_float = float(change_percent_str)
        # 涨跌幅百分比
        delta_text = f"{change_float:.2f}%"

        if change_float > 0:
            color = 'inverse'  # Streamlit metric 默认绿色代表负面，红色代表正面
        elif change_float < 0:
            color = 'normal'
        else:
            color = 'off'

        return color, delta_text

    except (ValueError, TypeError):
        return 'off', "N/A"


def plot_min_chart(min_data_df: pd.DataFrame, stock_name: str, close_price: float):
    """
    使用 Plotly 绘制分时价格和成交量图。
    """

    # ------------------ 价格图 ------------------
    fig_price = px.line(
        min_data_df,
        x='Time',
        y='Price',
        title=f'{stock_name} 分时价格走势',
        labels={'Price': '价格', 'Time': '时间'}
    )

    # 添加昨日收盘价参考线
    fig_price.add_hline(
        y=close_price,
        line_dash="dash",
        line_color="gray",
        annotation_text="昨收盘价",
        annotation_position="bottom right"
    )

    fig_price.update_layout(height=400, hovermode="x unified")
    fig_price.update_traces(line=dict(width=1.5))

    st.plotly_chart(fig_price, width='stretch')

    # ------------------ 成交量图 ------------------
    fig_volume = px.bar(
        min_data_df,
        x='Time',
        y='Volume_Per_Min',
        title='分时成交量',
        labels={'Volume_Per_Min': '成交量', 'Time': '时间'}
    )
    fig_volume.update_layout(height=200, hovermode="x unified")
    fig_volume.update_xaxes(showticklabels=False)  # 隐藏成交量图的X轴刻度，保持与价格图对齐

    st.plotly_chart(fig_volume, width='stretch')


def stock_min_data_page():

    # 默认值设置
    default_code = "sh600938"

    # -------------------- 输入参数区域 --------------------
    with st.form(key='min_data_form'):
        stock_code = st.text_input(
            "请输入股票代码 (Code)",
            value=default_code,
            placeholder="例如：sh600938",
            key="min_data_code"
        ).strip()

        submitted = st.form_submit_button("📊 查询分时数据")

    # -------------------- 数据获取和绘图 --------------------

    if submitted:
        if not stock_code:
            st.warning("请输入有效的股票代码。")
            return

        with st.spinner(f"正在加载 {stock_code} 的分时数据..."):
            realtime_info, min_data_raw = fetch_minute_data(stock_code)

            if realtime_info and min_data_raw:

                # ------------------- 1. 实时行情展示 -------------------
                st.markdown("### 实时行情概览")

                # 提取关键指标
                name = realtime_info.get('name', 'N/A')
                price = realtime_info.get('price', 'N/A')
                price_change = realtime_info.get('priceChange', '0.00')
                change_percent = realtime_info.get('changePercent', '0.00')
                close_prev = float(realtime_info.get('close', '0'))  # 昨收价

                color_mode, delta_percent_text = get_color_and_delta(change_percent)

                col1, col2, col3, col4, col5 = st.columns(5)

                col1.metric("现价", price, delta=f"{price_change} ({delta_percent_text})", delta_color=color_mode)
                col2.metric("昨收", realtime_info.get('close', 'N/A'))
                col3.metric("今开", realtime_info.get('open', 'N/A'))
                col4.metric("最高", realtime_info.get('high', 'N/A'))
                col5.metric("最低", realtime_info.get('low', 'N/A'))

                # ------------------- 2. 分时数据处理 -------------------
                st.markdown("---")
                st.markdown(f"### 分时走势图 - {name} ({stock_code})")

                # 将 minData 转换为 DataFrame
                # minData 格式: [ ["0930", "29.21", "3856", "11263376.00"], ... ]
                df_min = pd.DataFrame(min_data_raw, columns=["Time", "Price", "Volume_Per_Min", "Turnover_Cumulative"])

                # 转换为正确的类型
                for col in ["Price", "Volume_Per_Min", "Turnover_Cumulative"]:
                    df_min[col] = pd.to_numeric(df_min[col], errors='coerce')

                # 绘制图表
                if not df_min.empty:
                    plot_min_chart(df_min, name, close_prev)
                else:
                    st.info("分时数据列表为空，无法绘制图表。")

            else:
                st.info("未能成功获取分时数据。")


# 运行页面
if __name__ == '__main__':
    stock_min_data_page()