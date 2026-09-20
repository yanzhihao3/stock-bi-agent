# Stock BI Agent

智能股票查询与分析系统，支持 AI 对话、股票数据查询、新闻资讯、Redis 缓存、CI/CD 自动化。
内置 **OpenAI Agents SDK** 和 **LangChain + LangGraph** 双 AI 引擎，API 层一键切换。
自带**工具选择评测体系**：把「模型有没有选对工具」变成可量化、可复现的指标。

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

### 工具选择评测

把「模型有没有选对工具」从主观感觉变成可量化、可复现的指标。

- **评测集**：17 条用例，覆盖闲聊 / 单工具 / 易混淆 / 多工具 / 跨类组合 / 记忆 / 干扰 / 边界 8 类场景
- **判定字段**：`expect_tools`（必须调）、`optional_tools`（可选）、`forbid_tools`（禁止，支持 `stock_*` 通配）
- **指标**：严格准确率、工具召回率 / 精确率、违禁调用、平均工具调用数、平均回答正文、token 用量
- **分层跑**：`--category` / `--tag` / `--id` 只跑某一类或某几条；`--repeat` 对边界用例重复验证
- **实测**：两个引擎在 17 条上均为 **17/17**；langchain 引擎的 token 消耗约为 agents 的 **一半**

> 评测**没有**接进 CI —— 每次运行都会真实调用大模型与外部 API，成本随 push 频率累积。
> 改动提示词 / 工具描述后手动跑一次即可（见「测试」一节）。

### 回答数字一致性核对

工具选择评测量的是「有没有选对工具」（过程指标），这一层量的是「有没有说错数字」（结果指标）。

- **做法**：拿工具返回里的数字当标准答案，去核对模型回答正文里的数字 —— 纯本地字符串/数值处理，**不消耗任何 token**
- **前提**：轨迹里要有 `tool_results`（工具返回）和 `answer`（完整回答），两个引擎都在写
- **只出可疑清单**：模型自己算出的数字、单位换算（工具返回万元、回答写亿元）都会误报；量级差异和"同一数字的粗略复述"会被单独归类，不混进可疑里

```bash
python eval/check_numbers.py                                    # 扫日常对话轨迹
python eval/check_numbers.py --trace-path logs/eval-traces.jsonl # 扫评测跑批的轨迹
```

### 可观测性（日志 + request id + 工具健康度）

- **统一日志**：`services/observability.py` 用 `dictConfig` 配好双通道 —— 控制台 INFO、文件 DEBUG（`logs/app-<service>.log`，10MB × 5 轮转）。
  在此之前项目**没有配过日志**：`logger.warning/exception` 只打到 stderr、不落盘，`logger.info/debug` 更是被直接丢弃。
- **request id 贯穿**：`ContextVar` + `logging.Filter`，格式为 `时间 级别 [request_id] 模块: 消息`。
  对话请求的 id 直接用 `session_id` —— 日志、`logs/traces.jsonl`、数据库三边同名，`grep` 一个值就能捞出从接口到模型到工具的完整链路。
  按 asyncio 任务隔离（并发不串号），后台任务（记忆提取）继承创建时的 id。
- **工具健康度**：`summarize_tool_output()` 判定每次工具返回是「空」还是「错」，确实为空/错时记一条**不含返回正文**的 warning，并在轨迹里留下 `size/empty/error` 字段；`eval/report.py` 汇总成报表。

```bash
python eval/report.py                                           # 日常对话的健康度报表
python eval/report.py --trace-path logs/eval-traces.jsonl        # 看评测跑批
python eval/report.py --all-tools                                # 正常的工具也列出来
```

> Windows PowerShell 读日志要显式指定编码，否则中文会变乱码：
> `Get-Content logs\app-server.log -Tail 20 -Encoding UTF8`
> （日志文件本身是 UTF-8；`rg`、VS Code 直接打开都正常）

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
│   ├── observability.py    # 日志配置 + request id 贯穿 + 出口脱敏
│   ├── config.py           # 跨进程地址配置（MCP 服务地址）
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
├── eval/                   # 工具选择评测
│   ├── golden_set.yaml     # 评测集（17 条用例 / 8 类场景）
│   ├── run_eval.py         # 跑批 + 判定 + 报告
│   ├── concurrency_check.py# MCP 共享连接的并发安全检查
│   ├── check_numbers.py    # 回答数字一致性核对（离线，0 token）
│   ├── report.py           # 可观测性报表（延迟/token/工具健康度）
│   └── replay_memory.py    # 复现一次记忆提取（排查用）
├── scripts/
│   ├── db_status.py        # 看当前连的哪个库、表建了没、各表多少行
│   └── migrate_sqlite_to_mysql.py  # SQLite → MySQL 数据迁移
├── conftest.py             # pytest 全局配置（加载 .env）
└── .github/workflows/      # GitHub Actions CI/CD
```

## 测试

**单元测试**（134 个，全部是纯函数测试，不需要外部服务）：

```bash
pytest test/
```

**工具选择评测**（会真实调用大模型与外部 API，需要先启动 `main_mcp.py`）：

```bash
python eval/run_eval.py --engine agents                            # 全量 17 条，约 3 分钟
python eval/run_eval.py --engine agents --tag 难题                 # 只跑 6 条难题，约 1 分钟
python eval/run_eval.py --engine agents --id stock-04 --repeat 3   # 单条重复跑，看稳定性
python eval/run_eval.py --engine langchain                         # 换引擎做对比
```

加 `--min-accuracy 0.9` 可以让脚本在准确率低于阈值时返回非零退出码（供外部门禁调用）。

每次 push 到 GitHub，CI 会自动运行单元测试并构建 Docker 镜像。

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
  ⚠️ 免费第三方聚合服务，稳定性无保证（实测多个接口返回 404 / 503）。
  工具失败时返回空列表并记一条 warning 日志，用户侧表现为"没查到"。

## 数据库

**业务库**默认用 SQLite（`assert/sever.db`），**不配任何东西就能跑**。想换 MySQL
只需在 `.env` 里加一行，代码不动：

```
DATABASE_URL=mysql+pymysql://root:密码@127.0.0.1:3306/stock_bi?charset=utf8mb4
```

```bash
# 建库（必须是 utf8mb4，否则中文会存成问号）
mysql -u root -p -e "CREATE DATABASE stock_bi DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

python scripts/db_status.py                          # 确认连的是哪个库、表建了没
python scripts/migrate_sqlite_to_mysql.py --check    # 迁移前先核对行数，不写数据
python scripts/migrate_sqlite_to_mysql.py            # 迁数据
```

回退成本为零：把 `.env` 里那行删掉就又回到 SQLite，源库全程没被改过。

> ⚠️ **Agents SDK 的记忆库 `assert/conversations.db` 不跟着迁**。那是 SDK 自带的
> SQLite 实现（`AdvancedSQLiteSession`），表结构不受本项目控制 —— 换不动，也不该换。
> 所以换到 MySQL 后是「业务数据在 MySQL、会话记忆在本地 SQLite」的双库结构。
