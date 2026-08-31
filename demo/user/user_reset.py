import streamlit as st
import requests

from demo.common import API_BASE_URL, auth_headers


def alter_user(user_name, user_role, status):
    response = requests.post(
        f"{API_BASE_URL}/v1/users/reset-info",
        headers=auth_headers(),
        json={"user_name": user_name, "user_role": user_role, "status": status},
    ).json()
    return response["code"] == 200, response.get("message", "修改失败")


def page():
    if not st.session_state.get("logged", False):
        st.info("请先登录")
        return

    if st.session_state.get("user_role") != "管理员":
        st.warning("该操作需要管理员权限。")
        return

    with st.form(key="reset_info_form"):
        target = st.text_input("目标用户名", placeholder="要修改的用户")
        role = st.selectbox("用户类型", options=["普通用户", "管理员"])
        status = st.checkbox("账号有效", True)
        submitted = st.form_submit_button("修改信息")

        if submitted:
            if not target:
                st.error("请填写目标用户名")
                return
            with st.spinner("正在修改..."):
                ok, message = alter_user(target, role, status)
                if ok:
                    st.success(message)
                else:
                    st.error(message)


if __name__ == "__main__":
    page()
