# Stock BI Agent

智能股票查询与分析系统，支持 AI 对话、股票数据查询、新闻资讯、Redis 缓存、CI/CD 自动化。
内置 **OpenAI Agents SDK** 和 **LangChain + LangGraph** 双 AI 引擎，API 层一键切换。

## 功能特性

### 股票服务
- 股票代码/名称模糊查询
- 行业板块信息查询
- 股票排名、K线图（日/周/月）
- 自选股管理

### AI 对话 — 双引擎
- **Agents 引擎**：OpenAI Agents SDK，MCP 原生支持
- **LangChain 引擎**：LangChain + LangGraph ReAct Agent
- 通用对话、股票分析、CSV/Excel 问答、论文总结、多模态

### 实用工具
- 今日要闻、抖音热点、GitHub 热榜
- 每日名言、励志语录
- 城市天气预报

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入你的 API Key：

```bash
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-max
```

### 3. 启动 Redis（可选，不启动则自动降级为直调 API）

```bash
docker run -d -p 6379:6379 --name redis-stock redis:7
```

### 4. 启动后端服务

```bash
python main_server.py          # FastAPI 后端 (端口 8000)
python main_mcp.py             # MCP 服务聚合 (端口 8900)
streamlit run demo/streamlit_demo.py  # 前端 (端口 8501)
```

## 引擎切换

前端侧边栏选择 `AI 引擎` 下拉框，或 API 请求加参数：

```json
POST /v1/chat/
{ "engine": "langchain", "content": "查一下贵州茅台", ... }
```

| 引擎 | 值 | 说明 |
|------|-----|------|
| OpenAI Agents SDK | `agents` | 默认，原生 MCP 支持 |
| LangChain + LangGraph | `langchain` | ReAct Agent，工具循环自动编排 |

## 项目结构

```
.
├── main_server.py          # FastAPI 主服务 (端口 8000)
├── main_mcp.py             # MCP 服务聚合器 (端口 8900)
├── services/
│   ├── chat.py             # AI 对话 — Agents SDK 引擎
│   ├── langchain_chat.py   # AI 对话 — LangChain + LangGraph 引擎
│   ├── chat_common.py      # 公共函数（模板、工具分类、DB操作）
│   ├── mcp_adapter.py      # MCP SSE → LangChain 工具适配器
│   ├── redis_client.py     # Redis 缓存客户端
│   └── schema_normalizer.py# 响应数据规范化
├── api/                    # MCP 工具服务
│   ├── autostock.py        # 股票数据（带 Redis 缓存）
│   ├── news.py             # 新闻
│   ├── saying.py           # 名言
│   └── tool.py             # 实用工具
├── routers/                # API 路由
├── agent/                  # AI Agent 模块
├── demo/                   # Streamlit 前端
├── models/                 # 数据模型
├── test/                   # 单元测试
└── .github/workflows/      # GitHub Actions CI/CD
```

## 测试

```bash
# 运行单元测试（22 个测试，不需要外部依赖）
pytest test/test_schema_normalizer.py test/test_redis_client.py -v

# 运行所有测试
pytest test/
```

每次 push 到 GitHub，CI 会自动运行测试。

## 技术栈

| 分类 | 技术 |
|------|------|
| 后端框架 | FastAPI, Uvicorn |
| AI 引擎 | OpenAI Agents SDK / LangChain + LangGraph |
| MCP 协议 | FastMCP |
| 前端 | Streamlit |
| 缓存 | Redis (redis-py) |
| 数据库 | SQLAlchemy + SQLite |
| 数据处理 | pandas, numpy, plotly |
| 容器化 | Docker, Docker Compose |
| CI/CD | GitHub Actions (pytest + Docker build) |
| LLM | 阿里云通义千问 (Qwen) |

## Redis 缓存策略

| 接口 | 过期时间 | 说明 |
|------|---------|------|
| 股票/指数代码 | 1 小时 | 几乎不变 |
| 行业板块/大盘数据 | 5-10 分钟 | 盘中相对稳定 |
| 股票排行 | 1 分钟 | 交易时段变化较快 |
| K 线数据 | 5-10 分钟 | 历史数据不变 |
| 分时数据 | 30 秒 | 近实时 |

Redis 不可用时自动降级为直调外部 API，不影响服务。

## 外部 API

- **autostock.cn** - 股票数据（K线、排名、板块等）
- **whyta.cn** - 新闻、名言、实用工具

## 数据库

默认使用 SQLite，存储路径：`assert/sever.db`
