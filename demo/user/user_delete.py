import streamlit as st
import requests

from demo.common import API_BASE_URL, auth_headers


def delete_self():
    response = requests.post(
        f"{API_BASE_URL}/v1/users/delete",
        headers=auth_headers(),
    ).json()
    return response["code"] == 200, response.get("message", "删除失败")


def page():
    if not st.session_state.get("logged", False):
        st.info("请先登录")
        return

    st.info(f"您已登录为 **{st.session_state['user_name']}**。")
    st.warning("此操作将永久删除当前账户，无法恢复！")

    if st.button("删除我的账户"):
        with st.spinner("正在删除..."):
            ok, message = delete_self()
            if ok:
                st.success(message)
                st.session_state["logged"] = False
                st.session_state["user_name"] = None
                st.session_state["token"] = None
                st.session_state["user_role"] = None
                st.rerun()
            else:
                st.error(message)


if __name__ == "__main__":
    page()
