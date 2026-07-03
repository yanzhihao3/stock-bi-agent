import streamlit as st
import time, requests
# 一句话总结：当前登录用户可以修改自己的用户类型（普通用户/管理员）和账户状态（启用/禁用）。
def alter_user(user_name, user_role, status):
    response = requests.post(
        "http://127.0.0.1:8000/v1/users/reset-info",
        json={"user_name": user_name, "user_role": user_role, "status": status}
    ).json()

    st.write(response)

    if response['code'] == 200:
        return True
    else:
        # 模拟登录失败
        return False

def user_login_page():
    # 未登录时显示登录表单
    with st.form(key='login_form'):
        role = st.selectbox("用户类型",options=["普通用户", "管理员"])
        status = st.checkbox("是否有效", True)

        # 登录按钮
        submitted = st.form_submit_button("修改信息")

        if submitted:
            # 使用 Spinner 显示加载状态
            with st.spinner("正在验证凭证..."):
                if alter_user(st.session_state['user_name'], role, status):
                    st.success(f"修改成功！")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error("修改失败！")

if __name__ == '__main__':
    user_login_page()