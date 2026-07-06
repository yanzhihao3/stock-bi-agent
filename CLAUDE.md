# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Stock BI Agent

智能股票查询与分析系统，基于 FastMCP + FastAPI + Streamlit 构建，集成 Redis 缓存与 CI/CD 自动化。

## 技术架构

```
用户浏览器 (Streamlit / API)
       │
       ▼
FastAPI 后端 (端口 8000)
  ├── routers/         API 路由
  ├── services/        业务逻辑
  │   ├── chat.py              AI 对话（Agents SDK 引擎）
  │   ├── langchain_chat.py    AI 对话（LangChain + LangGraph 引擎）
  │   ├── chat_common.py       公共函数（模板、工具分类、DB操作）
  │   ├── mcp_adapter.py       MCP SSE → LangChain 工具适配器
  │   ├── redis_client.py      Redis 缓存层
  │   └── schema_normalizer    数据规范化
  ├── models/          数据模型
  └── /stock           股票 API（带 Redis 缓存）
       │
       ▼ (MCP 工具调用)
MCP 服务聚合器 (main_mcp.py, 端口 8900)
  ├── autostock.py  股票数据 (autostock.cn API)
  ├── news.py       新闻服务 (whyta.cn API)
  ├── saying.py     名言服务 (whyta.cn API)
  └── tool.py       实用工具  (whyta.cn API)
```

## 核心模块

### Redis 缓存层 (`services/redis_client.py`)
- 异步 Redis 连接管理（连接失败自动降级）
- `cached_get()` / `cached_post()` 封装 HTTP 调用 + 缓存
- 按接口配置不同的 TTL（30s ~ 1h）
- Redis 不可用时不影响业务

### MCP 工具服务 (`api/`)
- `autostock.py` - 股票数据查询（K线、排名、板块等），Token: `zgaLG8unUPr`
- `news.py` - 今日要闻、抖音热点、GitHub热榜等，Token: `6d997a997fbf`
- `saying.py` - 名言鸡汤服务，Token: `6d997a997fbf`
- `tool.py` - 城市天气、电话归属地、汇率换算等，Token: `6d997a997fbf`

### MCP 聚合 (`main_mcp.py`)
- 通过 `FastMCP.from_fastapi()` 将 FastAPI 应用转为 MCP 服务器
- 使用 `mcp.import_server()` 合并多个 MCP 服务（news, saying, tool）
- 对外暴露统一 MCP 接口，AI 无需知道工具来源
- SSE 传输协议，端口 8900

### AI 对话核心 — 双引擎架构

支持在 API 层通过 `engine` 参数切换两套 AI 引擎：

- **agents 引擎** (`services/chat.py`) — 使用 OpenAI Agents SDK
  - `MCPServerSse` 连接 MCP 服务，通过 `ToolFilterStatic` 按任务类型过滤工具
  - `AdvancedSQLiteSession` 存储 Agent 对话状态
  - 流式输出：`Runner.run_streamed()` + `ResponseTextDeltaEvent`

- **langchain 引擎** (`services/langchain_chat.py`) — 使用 LangChain + LangGraph
  - `mcp_adapter.py` 将 MCP 工具包装为 LangChain `BaseTool`
  - `create_react_agent()` 构建 ReAct Agent 自动循环工具调用
  - 流式输出：`astream_events()` 监听 `on_chat_model_stream`/`on_tool_start`/`on_tool_end`

- **公共模块** (`services/chat_common.py`) — 两个引擎共用
  - 工具分类：`TOOL_CATEGORIES` 定义了股票分析、新闻聚合、通用工具、名言鸡汤四类
  - 时间签名系统提示词模板渲染
  - 数据库操作（会话、消息持久化）
  - 可视化工具（K线等）走 `stop_on_first_tool`，抑制 LLM 多余文字输出

### Agent 模块 (`agent/`)
- `stock_agent.py` - 股票分析 Agent
- `csv_agent.py` - CSV 文件问答
- `excel_agent.py` - Excel 文件问答
- `summary_agent.py` - 论文总结
- `vison_agent.py` - 多模态图片问答

### 系统提示词模板 (`templates/`)
- `chat_start_system_prompt.jinja2` - Jinja2 模板
- 通过时间签名（hash）防止 AI 凭空生成时间信息
- 任务类型不同，提示词不同（股票分析/数据BI/通用聊天）

### 数据模型
- `models/data_models.py` - Pydantic 模型（API 请求/响应）
- `models/orm.py` - SQLAlchemy ORM 模型（数据库表）

### 数据库
- `assert/sever.db` - 用户、会话、消息数据
- `assert/conversations.db` - Agent 记忆（AdvancedSQLiteSession）

### CI/CD (`.github/workflows/ci.yml`)
- push/PR 到 main 自动触发
- job 1: 在 Python 3.10/3.11 上运行 pytest（22 个单元测试）
- job 2: 测试通过后构建 Docker 镜像

## 启动方式

```bash
# Redis（可选，不启动则自动降级）
docker run -d -p 6379:6379 --name redis-stock redis:7

# 后端服务 (端口 8000)
python main_server.py

# MCP 服务 (端口 8900)
python main_mcp.py

# 前端 (端口 8501)
streamlit run demo/streamlit_demo.py
```

## 环境变量

```bash
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-max
OPENAI_VISON_MODEL=qwen-vl
REDIS_URL=redis://localhost:6379/0   # 可选，默认值
AUTOSTOCK_TOKEN=zgaLG8unUPr          # 可选，有默认值
WHYTA_TOKEN=6d997a997fbf             # 可选，有默认值
```

支持从 `.env` 文件自动加载（python-dotenv）。
# ...

## 依赖

```bash
# 核心
agents>=1.4.0           # OpenAI Agents SDK
fastapi>=0.122.0        # API 框架
fastmcp==2.13.1         # MCP 服务
langchain>=1.2.0        # LangChain 引擎
langchain-openai>=1.2.0 # LangChain OpenAI 适配
langgraph>=1.1.0        # LangGraph Agent
# 其他见 requirements.txt
```

## 测试

```bash
# 运行单元测试（22 个，不需要外部依赖）
pytest test/test_schema_normalizer.py test/test_redis_client.py -v

# 运行所有测试
pytest test/
```

## 外部 API

### autostock.cn（股票数据）
- Token: `zgaLG8unUPr`（硬编码在 `api/autostock.py`）
- API 文档: https://s.apifox.cn/c3278b4f-5629-4732-858c-36758ff5d083/api-147275957
- 注册入口: https://www.autostock.cn

### whyta.cn（新闻/名言/工具）
- Token: `6d997a997fbf`（硬编码在 `api/news.py`, `api/saying.py`, `api/tool.py`）
- API 文档: https://apis.whyta.cn/
