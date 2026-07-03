# 导入 Streamlit 库
import streamlit as st

# 一句话总结：这是应用的"总控台"，根据用户是否登录，显示不同的导航菜单，管理所有页面的跳转。

if "logged" not in st.session_state:
    st.session_state.logged = False
    # 作用：首次运行时，在全局状态中初始化logged变量为False（未登录）

# --- 账户中心 ---定义账户中心页面
# st.Page(
#     "文件路径",      # 要加载的Python文件
#     title="显示标题", # 菜单中显示的文字
#     icon="图标"       # 菜单项前的图标)
page_user_register = st.Page("user/user_register.py", title="用户注册", icon="➕")
page_user_login = st.Page("user/user_login.py", title="登陆/退出", icon="🚪")
page_user_info = st.Page("user/user_info.py", title="个人信息", icon="👤")
page_user_reset = st.Page("user/user_reset.py", title="修改信息", icon="✏️")
page_user_delete = st.Page("user/user_delete.py", title="删除账户", icon="❌")
page_user_list = st.Page("user/user_list.py", title="列举账户", icon="👥")

# --- 股票中心 ---定义股票中心页面
page_stock_search = st.Page("stock/stock_search.py", title="股票搜索", icon="🔍")
page_stock_industry = st.Page("stock/stock_industry.py", title="行业概览", icon="🏷️")
page_stock_board = st.Page("stock/stock_board.py", title="市场看板", icon="🧩")
page_stock_rank = st.Page("stock/stock_rank.py", title="股票排行", icon="🏆")
page_stock_info = st.Page("stock/stock_info.py", title="股票信息", icon="ℹ️")
page_stock_kline = st.Page("stock/stock_kline.py", title="股票K线图", icon="📊")
page_stock_min = st.Page("stock/stock_min_data.py", title="当日交易", icon="📊")
page_stock_fav = st.Page("stock/stock_favorite.py", title="股票收藏", icon="⭐")

# --- 数据中心 ---
page_data_list = st.Page("data/data_list.py", title="数据列表", icon="📑")
page_data_manage = st.Page("data/data_manage.py", title="数据管理", icon="⚙️")

# --- 智能问答 ---
page_chat_list = st.Page("chat/chat_list.py", title="对话历史", icon="🕰️")
page_chat = st.Page("chat/chat.py", title="通用对话", icon="💬")

mcp_list = st.Page("mcp/mcp_list.py", title="MCP列表", icon="⚙️")
mcp_debug = st.Page("mcp/mcp_debug.py", title="MCP调试", icon="🐞")

# 根据登录状态构建导航菜单（核心逻辑）
# st.navigation({
#     "分组名称1": [页面1, 页面2, ...],
#     "分组名称2": [页面3, 页面4, ...],})
# 字典的键是侧边栏的分组标题
# 字典的值是该分组下的页面列表
if st.session_state.logged:
    # # 已登录：显示完整菜单
    pg = st.navigation(
        {
            "账户中心": [page_user_login, page_user_info, page_user_reset, page_user_delete, page_user_list],
            "股票中心": [page_stock_search, page_stock_board, page_stock_industry, page_stock_rank, page_stock_info, page_stock_kline, page_stock_min, page_stock_fav],
            "数据中心": [page_data_list, page_data_manage],
            "工具中心": [mcp_list, mcp_debug],
            "智能问答": [page_chat_list, page_chat],
        }
    )
else:
    # 未登录：显示简化菜单（无数据中心、无工具中心）
    pg = st.navigation(
        {
            "账户中心": [page_user_register, page_user_login],
            "股票中心": [page_stock_search, page_stock_board, page_stock_industry, page_stock_rank, page_stock_info, page_stock_kline, page_stock_min, page_stock_fav],
            "智能问答": [page_chat_list, page_chat],
        }
    )

pg.run()
# 作用：启动导航系统，在侧边栏显示菜单，用户点击后加载对应页面