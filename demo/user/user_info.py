import streamlit as st
import time, requests

# 一句话总结：当前登录用户可以查看自己的用户信息（如用户ID、角色、注册时间等）。

def get_user(user_name):
    response = requests.post(
        "http://127.0.0.1:8000/v1/users/info", # 把0.0.0.0改了
        params={"user_name": user_name}
    ).json()

    st.write(response)

    if response['code'] == 200:
        return True
    else:
        return False

if st.session_state.get('logged', False):
    get_user(st.session_state['user_name'])
