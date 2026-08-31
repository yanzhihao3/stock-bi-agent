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
  │   ├── chat_common.py       公共函数（模板、工具分类、DB操作、记忆注入/清理）
  │   ├── memory.py            用户级长期记忆（批量提取、注入、清理）
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
  - `SafeSQLiteSession`（继承 `AdvancedSQLiteSession`）存储对话状态，读取历史时自动清洗悬空工具序列，避免模型 400
  - 工具执行后使用 `run_llm_again`：同一轮内生成最终回答（不使用 stop_on_first_tool）
  - 失败兜底：异常时输出友好文案并清空该会话 AI 记忆（自愈），不产生脏数据
  - 流式输出：`Runner.run_streamed()` + `ResponseTextDeltaEvent`

- **langchain 引擎** (`services/langchain_chat.py`) — 使用 LangChain + LangGraph
  - `mcp_adapter.py` 将 MCP 工具包装为 LangChain `BaseTool`
  - `create_react_agent()` 构建 ReAct Agent 自动循环工具调用
  - 流式输出：`astream_events()` 监听 `on_chat_model_stream`/`on_tool_start`/`on_tool_end`

- **公共模块** (`services/chat_common.py`) — 两个引擎共用
  - 工具分类：`TOOL_CATEGORIES` 定义了股票分析、新闻聚合、通用工具、名言鸡汤四类
  - 时间签名系统提示词模板渲染
  - 数据库操作（会话、消息持久化）
  - `get_init_message()` 注入用户长期记忆段落
  - `clear_agent_session_memory()` 清空 conversations.db 中某会话的 AI 记忆（删会话/删用户/失败自愈时调用）
  - `delete_chat_session()` 删除业务数据后连带清理 AI 记忆，避免孤儿数据

### 用户级长期记忆 (`services/memory.py`)
- 数据表：`user_memory`（user_id / key / content / updated_at），每个用户一本"记事本"
- 提取：每轮对话后在后台批量提取，未处理消息攒够 `MEMORY_BATCH_SIZE`（默认 10）条才调一次模型
- 游标：存于 `user_memory` 表 key=`__cursor__` 的特殊记录，标记已处理到哪条消息
- 动作：模型输出 JSON 动作数组，支持 add / update（同 key 覆盖）/ delete（清除过时记忆）
- 注入：`get_init_message(task, user_name)` 把记忆拼进系统提示词，两个引擎共用
- 清理：删除用户时级联删除 user_memory；删除会话/用户时同步清理 conversations.db，避免孤儿数据
- 配置：`MEMORY_ENABLED`、`MEMORY_BATCH_SIZE`、`MEMORY_MAX_ITEMS`、`MEMORY_MODEL`

### 系统提示词模板 (`templates/`)
- `chat_start_system_prompt.jinja2` - Jinja2 模板
- 通过时间签名（hash）防止 AI 凭空生成时间信息
- 任务类型不同，提示词不同（股票分析/数据BI/通用聊天）

### 数据模型
- `models/data_models.py` - Pydantic 模型（API 请求/响应）
- `models/orm.py` - SQLAlchemy ORM 模型（数据库表）

### 数据库
- `assert/sever.db` - 用户、会话、消息、自选股、长期记忆（user_memory）
- `assert/conversations.db` - Agent 记忆（SafeSQLiteSession）
- 删除会话/用户时：业务数据 + conversations.db 同步清理，无孤儿数据

### CI/CD (`.github/workflows/ci.yml`)
- push/PR 到 main 自动触发
- job 1: 在 Python 3.10/3.11 上运行 pytest（39 个单元测试）
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
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
OPENAI_VISON_MODEL=qwen-vl
REDIS_URL=redis://localhost:6379/0   # 可选，默认值
AUTOSTOCK_TOKEN=...                  # 小熊股票 API token
WHYTA_TOKEN=6d997a997fbf             # 可选，有默认值
MEMORY_ENABLED=1                     # 长期记忆总开关（0 关闭）
MEMORY_BATCH_SIZE=10                 # 攒够多少条未处理消息才提取
MEMORY_MAX_ITEMS=30                  # 每用户最多保留记忆条数
MEMORY_MODEL=                        # 提取用模型，默认同 OPENAI_MODEL
MAX_TOOL_CALLS=5                     # 单轮工具调用上限
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
# 运行单元测试（39 个，不需要外部依赖）
pytest test/

# 运行所有测试
pytest test/
```

## 外部 API

### autostock.cn（股票数据）
- Token: 通过环境变量 `AUTOSTOCK_TOKEN` 配置（见 .env，不再硬编码）
- API 文档: https://s.apifox.cn/c3278b4f-5629-4732-858c-36758ff5d083/api-147275957
- 注册入口: https://www.autostock.cn

### whyta.cn（新闻/名言/工具）
- Token: 通过环境变量 `WHYTA_TOKEN` 配置（见 .env，不再硬编码）
- API 文档: https://apis.whyta.cn/
