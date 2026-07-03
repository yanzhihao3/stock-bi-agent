import os

# 从 .env 文件或系统环境变量读取配置
# 参考 .env.example 设置你的 API Key
if not os.environ.get("OPENAI_API_KEY"):
    raise ValueError("请设置 OPENAI_API_KEY 环境变量，参考 .env.example")

import uvicorn
from fastapi import FastAPI  # type: ignore
from routers.user import router as user_routers
from routers.chat import router as chat_routers
from routers.data import router as data_routers
from routers.stock import router as stock_routers

from api.autostock import app as stock_app

app = FastAPI()

# 这是你的股票+聊天+用户管理综合服务的启动文件，把所有路由模块整合到一起，启动服务器。

@app.get("/v1/healthy")
def read_healthy():
    pass

# 自定义的模块挂载在一起 作用：把各个功能模块的路由注册到主应用
app.include_router(user_routers)
app.include_router(chat_routers)
app.include_router(data_routers)
app.include_router(stock_routers)

app.mount("/stock", stock_app) # 底层stock api 接口
# 将你之前写的 api.autostock 股票数据服务挂载到 /stock 路径下
# 访问方式：http://localhost:8000/stock/get_stock_code?keyword=茅台

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    # uvicorn main_server:app
