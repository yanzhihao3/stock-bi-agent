import streamlit as st
import requests

from demo.common import API_BASE_URL


def authenticate_user(user_name, password):
    response = requests.post(
        f"{API_BASE_URL}/v1/users/login",
        json={"user_name": user_name, "password": password},
    ).json()

    if response["code"] == 200:
        data = response["data"]
        st.session_state["logged"] = True
        st.session_state["user_name"] = user_name
        st.session_state["token"] = data["token"]
        st.session_state["user_role"] = data["user_role"]
        return True, response["message"]
    return False, response.get("message", "登录失败")


def user_login_page():
    if st.session_state.get("logged", False):
        st.info(
            f"您已登录为 **{st.session_state['user_name']}**"
            f"（角色：{st.session_state.get('user_role', '普通用户')}）。"
        )
        if st.button("退出登录"):
            st.session_state["logged"] = False
            st.session_state["user_name"] = None
            st.session_state["token"] = None
            st.session_state["user_role"] = None
            st.session_state["session_id"] = None
            st.session_state["messages"] = []
            st.rerun()
        return

    with st.form(key="login_form"):
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")
        submitted = st.form_submit_button("登录")

        if submitted:
            if not username or not password:
                st.error("用户名和密码不能为空！")
                return
            with st.spinner("正在验证凭证..."):
                ok, message = authenticate_user(username, password)
                if ok:
                    st.success(f"{message} 欢迎，{username}！")
                    st.rerun()
                else:
                    st.error(message)


if __name__ == "__main__":
    user_login_page()
