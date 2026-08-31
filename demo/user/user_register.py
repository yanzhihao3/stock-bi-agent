import streamlit as st
import requests

from demo.common import API_BASE_URL


def register_user(user_name, password):
    response = requests.post(
        f"{API_BASE_URL}/v1/users/register",
        json={"user_name": user_name, "password": password},
    ).json()

    if response["code"] == 200:
        data = response["data"]
        st.session_state["logged"] = True
        st.session_state["user_name"] = user_name
        st.session_state["token"] = data["token"]
        st.session_state["user_role"] = data["user_role"]
        return True, response["message"]
    return False, response.get("message", "注册失败")


def page():
    if st.session_state.get("logged", False):
        st.info(
            f"您已注册并登录为 **{st.session_state['user_name']}**"
            f"（角色：{st.session_state.get('user_role')}）。"
        )
        return

    st.caption("提示：第一个注册的用户会自动成为管理员。")
    with st.form(key="register_form"):
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")
        submitted = st.form_submit_button("注册")

        if submitted:
            if not username or not password:
                st.error("用户名和密码不能为空！")
                return
            with st.spinner("正在注册..."):
                ok, message = register_user(username, password)
                if ok:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)


if __name__ == "__main__":
    page()
