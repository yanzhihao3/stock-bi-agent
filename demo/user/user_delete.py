import streamlit as st
import time, requests

# 一句话总结：当前登录用户可以删除自己的账户（危险操作，直接执行，无二次确认）。

def delete_user(user_name):
    response = requests.post(
        "http://127.0.0.1:8000/v1/users/delete",
        params={"user_name": user_name}
    ).json()

    st.write(response) # 在页面上显示API返回结果

    if response['code'] == 200:
        return True
    else:
        return False

def user_login_page():
    # 检查是否已登录
    if st.session_state.get('logged', False):
        st.info(f"您已登录为 **{st.session_state['user_name']}**。")

        # 退出按钮
        if st.button("删除用户"):
            delete_user(st.session_state['user_name'])
            st.session_state['logged'] = False  # 清除登录状态
            st.session_state['user_name'] = None  # 清除用户名
            time.sleep(0.5)  # 等待0.5秒
            st.rerun()  # 刷新页面
        return


if __name__ == '__main__':
    user_login_page()