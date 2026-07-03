# Stock BI Agent

智能股票查询与分析系统，支持 AI 对话、股票数据查询、新闻资讯、名言天气等多种功能。

## 功能特性

### 股票服务
- 股票代码/名称模糊查询
- 行业板块信息查询
- 股票排名、K线图（日/周/月）
- 自选股管理

### AI 对话
- 通用对话（集成 MCP 工具）
- 股票分析对话
- CSV/Excel 文件问答
- 论文总结与知识点生成
- 多模态图片问答

### 实用工具
- 今日要闻、抖音热点、GitHub 热榜
- 每日名言、励志语录
- 城市天气预报

## 项目结构

```
.
├── main_server.py          # FastAPI 主服务 (端口 8000)
├── main_mcp.py             # MCP 服务聚合器 (端口 8900)
├── api/                    # MCP 工具服务
│   ├── autostock.py        # 股票数据
│   ├── news.py             # 新闻
│   ├── saying.py          # 名言
│   └── tool.py            # 实用工具
├── routers/                # API 路由
├── services/               # 业务逻辑
├── models/                 # 数据模型
├── agent/                  # AI Agent 模块
├── demo/                   # Streamlit 前端
└── assert/                 # 数据库存储
```

## 快速启动

### 1. 配置环境变量

```bash
export OPENAI_API_KEY=your_api_key
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export OPENAI_MODEL=qwen-max
export OPENAI_VISON_MODEL=qwen-vl
```

### 2. 启动后端服务

```bash
python main_server.py
# 服务地址: http://localhost:8000
```

### 3. 启动 MCP 服务

```bash
python main_mcp.py
# 服务地址: http://localhost:8900
```

### 4. 启动前端

```bash
streamlit run demo/streamlit_demo.py
# 服务地址: http://localhost:8501
```

## API 接口

| 接口 | 说明 |
|------|------|
| `GET /v1/healthy` | 健康检查 |
| `POST /v1/chat/` | AI 对话（流式返回） |
| `POST /v1/user/login` | 用户登录 |
| `POST /v1/user/register` | 用户注册 |
| `GET /v1/stock/list` | 自选股列表 |
| `GET /stock/get_stock_code` | 股票代码查询 |

## 技术栈

- **FastAPI** - Web 框架
- **FastMCP** - MCP 协议实现
- **SQLAlchemy** - 数据库 ORM
- **Streamlit** - 前端界面
- **阿里云通义千问** - LLM 模型

## 数据库

默认使用 SQLite，存储路径：`assert/sever.db`
