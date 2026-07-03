import streamlit as st
import requests
# 这段代码是聊天历史列表页面，用于显示用户的所有历史对话记录。它与之前的 chat.py 是前后关联的两个页面。
# 一句话总结：这是一个对话历史管理页面，用户可以：
# 查看所有历史对话 点击进入某个对话继续聊天  删除不需要的对话

# 作用：只有登录用户才能查看自己的对话历史
if st.session_state.get('logged', False):
    # 已登录，显示内容
    st.sidebar.markdown(f"用户名：{st.session_state['user_name']}")

    # 2. 获取对话列表 API 调用：POST /v1/chat/list?user_name=张三
    data = requests.post("http://127.0.0.1:8000/v1/chat/list?user_name=" + st.session_state['user_name'])
    chat_data = data.json()["data"][::-1] # [::-1] 是反转列表，最新的在最上面

    # 为每个聊天会话创建卡片式展示
    for chat in chat_data:
        with st.container():  # 创建一个容器
            col1, col2, col3 = st.columns([3, 2, 1]) # 3列布局
            # 列1：会话信息 显示：会话ID、对话标题、创建时间
            with col1:
                st.markdown(f"**{chat['session_id']} / {chat['title']}**")
                st.caption(f"创建时间: {chat['start_time']}")

            with col2:
                feedback_text = "暂无反馈" if chat['feedback'] is None else chat['feedback']
                st.text(f"反馈: {feedback_text}")
            # 列3：操作按钮 进入聊天：保存 session_id 到状态，跳转到 chat.py 删除聊天：调用删除 API，刷新页面
            with col3:
                # 使用HTML a标签实现页面内跳转
                session_id = chat['session_id']
                st.session_state.session_id = session_id
                if st.button("进入聊天", key=session_id + "chat"):
                    st.switch_page("chat/chat.py")

                if st.button("删除聊天", key=session_id + "del"):
                    requests.post(
                        "http://127.0.0.1:8000/v1/chat/delete",
                        params={"session_id": session_id, "user_name": st.session_state['user_name']}
                    )

                    st.rerun()



            st.divider()

else:
    st.info("请先登录再使用模型～")