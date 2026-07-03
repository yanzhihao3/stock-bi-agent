import streamlit as st
import time, requests
# 一句话总结：提供登录表单，验证用户身份，登录成功后保存状态，并显示已登录界面。
def authenticate_user(user_name, password):
    content = requests.post(
        "http://127.0.0.1:8000/v1/users/login",
        json={"user_name": user_name, "password": password}
    )

    response = content.json()

    st.write(response)

    if response['code'] == 200:
        st.session_state['logged'] = True # 设置登录状态
        st.session_state['user_name'] = user_name # 保存用户名
        return True
    else:
        # 模拟登录失败
        return False

def user_login_page():
    # 检查是否已登录
    if st.session_state.get('logged', False): # 获取 'logged' 的值，没有则默认 False
        st.info(f"您已登录为 **{st.session_state['user_name']}**。")

        # 退出按钮
        if st.button("退出登录"):
            st.session_state['logged'] = False
            st.session_state['user_name'] = None
            st.rerun()  # 重新运行页面以显示未登录状态
        return

    # 未登录时显示登录表单
    with st.form(key='login_form'):
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")

        # 登录按钮
        submitted = st.form_submit_button("登录")

        if submitted:
            # 简单的输入校验
            if not username or not password:
                st.error("用户名和密码不能为空！")
                return

            # 使用 Spinner 显示加载状态
            with st.spinner("正在验证凭证..."):
                if authenticate_user(username, password):
                    st.success(f"登录成功！欢迎，{username}！")
                    time.sleep(0.5)
                    st.rerun()  # 重新运行以刷新导航栏和内容
                else:
                    st.error("登录失败：用户名或密码错误。")

if __name__ == '__main__':
    user_login_page()