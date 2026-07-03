import streamlit as st
import time, requests

def register_user(user_name, password, user_role):
    response = requests.post(
        "http://127.0.0.1:8000/v1/users/register", # 把0.0.0.0改了
        json={"user_name": user_name, "password": password, "user_role": user_role}
    ).json()
    st.write(response)
    if response['code'] == 200:
        st.session_state['logged_in'] = True
        st.session_state['user_name'] = user_name
        return True
    else:
        # 模拟登录失败
        return False

def page():

    # 未登录时显示登录表单
    with st.form(key='register_form'):
        username = st.text_input("用户名", placeholder="请输入用户名") # 密码输入框（隐藏输入）
        password = st.text_input("密码", type="password", placeholder="请输入密码")
        role = st.selectbox("用户类型",options=["普通用户", "管理员"])

        # 登录按钮
        submitted = st.form_submit_button("注册")

        if submitted:
            # 简单的输入校验
            if not username or not password:
                st.error("用户名和密码不能为空！")
                return

            # 使用 Spinner 显示加载状态
            with st.spinner("正在验证凭证..."):
                if register_user(username, password, role):
                    st.success(f"注册成功！欢迎，{username}！")
                    time.sleep(0.5)
                    st.rerun()  # 重新运行以刷新导航栏和内容
                else:
                    st.error("注册失败：用户名或密码错误。")

if __name__ == '__main__':
    page()