import streamlit as st
import time, requests
# 一句话总结：根据用户角色显示不同内容——管理员看到所有用户列表，普通用户看到"无权查看"提示。
def get_user(user_name):
    response = requests.post(
        "http://127.0.0.1:8000/v1/users/info",
        params={"user_name": user_name}
    ).json()

    if response["data"]["user_role"] == "管理员":
        # 是管理员：获取所有用户列表
        response = requests.post(
            "http://127.0.0.1:8000/v1/users/list",
            params={"user_name": user_name}
        ).json()

        st.dataframe(response["data"]) # 显示表格
    else:
        st.write("您是普通用户, 无权查看其他用户信息！")

    if response['code'] == 200:
        return True
    else:
        return False

if st.session_state.get('logged', False):
    get_user(st.session_state['user_name'])
