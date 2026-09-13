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
- 通用对话、股票数据分析

### 用户级长期记忆
- 跨会话记住用户身份、偏好、持仓等稳定信息（`user_memory` 表）
- 批量异步提取：未处理消息攒够 `MEMORY_BATCH_SIZE`（默认 10）条才调一次模型，不阻塞回答
- 支持加 / 改（同 key 覆盖）/ 删（过时记忆）三种动作，不重复堆积
- 每次对话自动注入「用户长期记忆」段落，新开会话也能记得用户
- 删除会话/用户时业务数据与 AI 记忆同步清理，无孤儿数据

### 用户认证 — JWT
- 登录/注册成功后签发 JWT（HS256），有效期默认 24 小时
- 业务接口通过 `Authorization: Bearer <token>` 鉴权，用户身份由 token 解析，不再信任客户端传入的用户名
- 角色体系：`管理员` / `普通用户`；用户列表、修改他人角色/状态等操作仅管理员可用
- 密码使用带盐 PBKDF2-SHA256 存储，兼容旧版无盐 SHA256（存量用户无需重置密码）
- 第一个注册的用户自动成为管理员（便于初始化），之后注册的用户默认为普通用户

### 实用工具
- 今日要闻、抖音热点、GitHub 热榜
- 每日名言、励志语录
- 城市天气预报

## 快速启动

### 方式一：Docker 一键启动（推荐）

依赖、环境、三个进程全部封装在一个镜像里，构建一次即可在任何装了 Docker 的机器上跑起来。

```bash
# 1. 准备配置。密钥不进镜像、不进 Git，只在运行时从 .env 注入
cp .env.example .env
# 编辑 .env，至少填 OPENAI_API_KEY / AUTOSTOCK_TOKEN / WHYTA_TOKEN / JWT_SECRET

# 2. 构建并启动（容器内：FastAPI 8000 + MCP 8900 + Streamlit 8501）
docker compose up -d --build

# 3. 查看状态，等 STATUS 从 health: starting 变成 healthy
docker compose ps
```

浏览器打开 <http://localhost:8501>。停止用 `docker compose down`。

几个设计要点：只对外暴露 8501，`8000`/`8900` 仅容器内部通信；SQLite 数据挂在 `./assert` 卷上，容器重建不丢；健康检查同时探测三个端口；`restart: unless-stopped` 让容器随 Docker 自动拉起。

### 方式二：手动启动三个进程

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入你的 API Key：

```bash
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
JWT_SECRET=change_me_to_a_long_random_string

# 长期记忆（可选）
MEMORY_ENABLED=1          # 0 关闭
MEMORY_BATCH_SIZE=10      # 攒够多少条未处理消息才提取
MEMORY_MAX_ITEMS=30       # 每用户最多保留记忆条数
MEMORY_MODEL=             # 提取用模型，默认同 OPENAI_MODEL
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

## 对话场景（task 参数）

前端侧边栏的 `对话场景` 是**可选约束**，默认 `自动（全部工具）`，对应请求体中的 `task` 字段：
- 不选（自动）→ 不传 `task`，后端全量开放工具，由 AI 根据问题自行选择，适合股票 + 天气这类混合问题
- 选具体场景 → 按分类缩小工具范围：`股票分析` 仅股票工具，`数据BI` 股票 + 通用工具，`通用聊天` 仅名言鸡汤

手动勾选具体工具时以勾选为准，优先级：勾选工具 > 场景分类 > 全量开放。

工具调用上限默认 5 次，防止 AI 无限循环调工具，可通过环境变量 `MAX_TOOL_CALLS` 调整。
工具执行后模型会继续生成最终回答（`run_llm_again`），同一轮即可看到结果，不会等下一轮。
对话失败时后端返回友好兜底文案，并自动清理该会话的 AI 记忆（自愈），不影响下次使用。

## 项目结构

```
.
├── main_server.py          # FastAPI 主服务 (端口 8000)
├── main_mcp.py             # MCP 服务聚合器 (端口 8900)
├── services/
│   ├── chat.py             # AI 对话 — Agents SDK 引擎
│   ├── langchain_chat.py   # AI 对话 — LangChain + LangGraph 引擎
│   ├── chat_common.py      # 公共函数（模板、工具分类、DB操作、记忆注入/清理）
│   ├── memory.py           # 用户级长期记忆（批量提取、注入、清理）
│   ├── auth.py             # JWT 鉴权（登录态校验）
│   ├── errors.py           # 统一错误响应
│   ├── mcp_adapter.py      # MCP SSE → LangChain 工具适配器
│   ├── redis_client.py     # Redis 缓存客户端
│   └── schema_normalizer.py# 响应数据规范化
├── api/                    # MCP 工具服务
│   ├── autostock.py        # 股票数据（带 Redis 缓存）
│   ├── news.py             # 新闻
│   ├── saying.py           # 名言
│   └── tool.py             # 实用工具
├── routers/                # API 路由
├── demo/                   # Streamlit 前端
├── models/                 # 数据模型
├── test/                   # 单元测试
└── .github/workflows/      # GitHub Actions CI/CD
```

## 测试

```bash
# 运行单元测试（39 个测试，不需要外部依赖）
pytest test/test_schema_normalizer.py test/test_redis_client.py test/test_auth.py test/test_chat_common.py test/test_jinja2_template.py test/test_errors.py -v

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
