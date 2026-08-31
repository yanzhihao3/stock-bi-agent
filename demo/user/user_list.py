import streamlit as st
import requests

from demo.common import API_BASE_URL, auth_headers


def page():
    if not st.session_state.get("logged", False):
        st.info("请先登录")
        return

    if st.session_state.get("user_role") != "管理员":
        st.warning("您是普通用户，无权查看用户列表。")
        return

    response = requests.post(
        f"{API_BASE_URL}/v1/users/list",
        headers=auth_headers(),
    ).json()

    if response["code"] == 200:
        st.dataframe(response["data"])
    else:
        st.error(response.get("message", "获取用户列表失败"))


if __name__ == "__main__":
    page()
