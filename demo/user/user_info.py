import streamlit as st
import requests

from demo.common import API_BASE_URL, auth_headers


def get_user_info():
    response = requests.post(
        f"{API_BASE_URL}/v1/users/info",
        headers=auth_headers(),
    ).json()

    if response["code"] == 200:
        st.json(response["data"])
    else:
        st.error(response.get("message", "获取用户信息失败"))


if st.session_state.get("logged", False):
    get_user_info()
else:
    st.info("请先登录")
