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
- `autostock.py` - 股票数据查询（K线、排名、板块等）。Token 走环境变量 `AUTOSTOCK_TOKEN`
- `news.py` - 今日要闻、抖音热点、GitHub热榜等。Token 走 `WHYTA_TOKEN`
- `saying.py` - 名言鸡汤服务。Token 走 `WHYTA_TOKEN`
- `tool.py` - 城市天气、电话归属地、汇率换算等。Token 走 `WHYTA_TOKEN`
- 共 22 个工具。K 线三兄弟（日/周/月）已合并为 `stock_get_kline(code, period)`，
  只在 MCP 层暴露给 AI；三个独立的 HTTP 路由保留给前端画图
- 工具失败不抛异常：返回空列表并记一条 warning，日志里**不含 URL 与 key**

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
- job 1: 在 Python 3.10/3.11 上运行 pytest（39 个单元测试），并注入测试用的假密钥
  （`JWT_SECRET` / `TIMESTAMP_SECRET` 在代码里是必填项，缺失会直接报错）
- job 2: 测试通过后构建 Docker 镜像
- ⚠️ **工具选择评测没有接进 CI**，这是有意的：每次运行都会真实调用大模型与外部 API，
  成本随 push 频率累积。改成"改动相关文件后手动跑一次"，见下面的「改动前后的约定」。

### 工具选择评测 (`eval/`)
- `golden_set.yaml` - 评测集，17 条用例覆盖 8 类场景（闲聊 / 单工具 / 易混淆 / 多工具 /
  跨类组合 / 记忆 / 干扰 / 边界）。判定字段：`expect_tools`（必须调）、
  `optional_tools`（可选）、`forbid_tools`（禁止，支持 `[__any__]` 特殊标记与
  `stock_*` 通配符）
- `run_eval.py` - 进程内驱动 `chat()`（不走 HTTP，避开 JWT），读轨迹比对期望，输出
  严格准确率 / 召回率 / 精确率 / 违禁调用 / 平均调用数 / 平均回答正文 / token 用量
- `concurrency_check.py` - 共享 MCP 连接下的并发安全检查，曾抓出 `connect()` 的建连竞态
- 当前基线：两个引擎在 17 条上都是 17/17；langchain 的 token 消耗约为 agents 的一半

### 回答数字一致性核对 (`eval/check_numbers.py`)
- 拿 `tool_results`（工具返回）里的数字当标准答案，核对 `answer`（回答正文）里的数字。
  纯本地处理，**不调用模型**。
- 轨迹字段由两个引擎写入：`services/chat.py` 的 `_extract_tool_results()`（工具名按
  调用顺序对齐，因为 `parallel_tool_calls=False` 保证串行）、`langchain_chat.py` 的
  `on_tool_end` 分支；截断长度见 `chat_common.truncate_for_trace()`
- 输出的是**可疑清单**不是判定结果。真出现量级差异（差 10 的整数次幂）和"同一数字的
  粗略复述"会被单独归类 —— 这两种多半无害，混进可疑清单会让噪音淹没真问题
- ⚠️ 调容差参数要小心：试过把量级容差放宽到 5%，结果 1500 被匹配成"某个成交额 10^4 倍
  的近似值"，一条真可疑的数字反而漏掉。**假阴性比假阳性危险**，`test/test_check_numbers.py`
  把这些边界锁住了

### 可观测性 (`services/observability.py` + `eval/report.py`)

- **这个模块出现之前，项目根本没配过日志** —— 11 个模块都有 `getLogger(__name__)`，
  但没有 handler，于是 warning/exception 只打 stderr、不落盘，info/debug 被丢弃。
  真实后果：K 线接口静默返回 `data:[]`，一直没人发现。
- 日志：`setup_logging("server" | "mcp" | "eval")`，控制台 INFO + 文件 DEBUG（轮转）。
  **必须在进程入口调一次**；`main_server.py` 放在模块级（这样 `uvicorn main_server:app` 也生效）。
- request id：`ContextVar` + `RequestIdFilter`，只留一个字段 ——
  普通请求用中间件生成的短 id，对话请求由 `routers/chat.py` 覆盖成 `session_id`。
- ⚠️ 改这一块前先看 `test/test_observability.py`，里面锁了四件事：
  流式链路里 set 的 id 能被内层引擎看到、并发不串号、后台任务继承 id、中间件请求后必须 reset。
  这些结论来自一次专门的探针验证（临时脚本，验完已删）。
- `services/chat.py` / `langchain_chat.py` 里还会**再绑一次** session_id：
  评测脚本直接调 `chat()`、不经过路由层，不兜底的话那些日志全是 `[-]`。
  位置刻意贴着 `try` —— 绑太早的话中间抛异常时 `finally` 跑不到，id 会残留。
- 工具健康度：`chat_common.summarize_tool_output()` 判定空/错，
  `log_tool_result()` 只记**工具名+参数摘要+大小+原因**，不记返回正文（正文在 traces.jsonl 里）。
  形状规则的真值表在 `test/test_tool_output.py`。
- `eval/report.py` 出健康度报表。**老轨迹没有判定字段时会单独计"未判定"**，
  不能默认当成正常 —— 否则真有故障时报表会显示一切健康。

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
WHYTA_TOKEN=...                      # 免费第三方，可能失效（见「外部 API」）
AUTOSTOCK_TOKEN=...                  # 付费股票数据接口
JWT_SECRET=...                       # 必填：缺失会直接启动失败
TIMESTAMP_SECRET=...                 # 必填：同上
MEMORY_ENABLED=1                     # 长期记忆总开关（0 关闭）
MEMORY_BATCH_SIZE=10                 # 攒够多少条未处理消息才提取
MEMORY_MAX_ITEMS=30                  # 每用户最多保留记忆条数
MEMORY_MODEL=                        # 提取用模型，默认同 OPENAI_MODEL
MAX_TOOL_CALLS=5                     # 单轮工具调用上限
```

支持从 `.env` 文件自动加载（python-dotenv）。
# ...

## 依赖

所有版本锁定在 `requirements.txt`，并与本机验证环境保持一致。核心部分：

```bash
openai-agents==0.13.6    # OpenAI Agents SDK（⚠️ 包名是 openai-agents，不是 agents）
langchain==1.2.18        # LangChain 引擎
langchain-openai==1.2.1  # LangChain OpenAI 适配
langgraph==1.1.10        # LangGraph Agent
fastapi==0.135.2         # API 框架
fastmcp==3.2.4           # MCP 服务端
mcp==1.27.0              # MCP 客户端 SDK（services/mcp_adapter.py 直接 import）
```

⚠️ PyPI 上另有一个叫 `agents` 的包，那是已退役的 TensorFlow Agents（强化学习），
装它会拖进 tensorflow + gym 约 700MB，且不提供本项目要用的 `Agent` / `Runner`。

## 测试

```bash
# 单元测试（39 个，不需要外部依赖）
pytest test/

# 工具选择评测（会真实调用大模型与外部 API，需要先启动 main_mcp.py）
python eval/run_eval.py --engine agents                            # 全量 17 条，约 3 分钟
python eval/run_eval.py --engine agents --tag 难题                 # 只跑 6 条难题，约 1 分钟
python eval/run_eval.py --engine agents --id stock-04 --repeat 3   # 单条重复跑，看稳定性
python eval/run_eval.py --engine langchain                         # 换引擎对比

# 并发安全检查（动了 MCP 连接相关代码后跑）
python eval/concurrency_check.py --n 3
```

## 改动前后的约定

改动下面这些内容后，**必须跑一次工具选择评测**确认没有退化：

```bash
python eval/run_eval.py --engine agents --tag 难题   # 6 条难题，约 1 分钟
```

- `services/chat_common.py` 的 `TOOL_CATEGORIES`（工具分类）
- `api/*.py` 里任何工具的 docstring —— **那就是模型看到的工具描述**
- `templates/chat_start_system_prompt.jinja2`（系统提示词）
- `MAX_TOOL_CALLS`、`temperature` 等影响模型行为的参数

原因：这些改动**不会让单元测试变红**（单测只覆盖代码逻辑），但会让模型选错工具或
多调工具 —— 只有评测能看出来。

## 外部 API

### autostock.cn（股票数据）
- Token: 通过环境变量 `AUTOSTOCK_TOKEN` 配置（见 .env，不再硬编码）
- API 文档: https://s.apifox.cn/c3278b4f-5629-4732-858c-36758ff5d083/api-147275957
- 注册入口: https://www.autostock.cn

### whyta.cn（新闻/名言/工具）
- Token: 通过环境变量 `WHYTA_TOKEN` 配置（见 .env，不再硬编码）
- API 文档: https://apis.whyta.cn/
- ⚠️ **免费第三方聚合服务，稳定性无保证**：2026-09 实测新闻、名言、花语等多个接口
  返回 404 / 503。工具失败时返回空列表并记一条 warning 日志，用户侧表现为"没查到"。
  排查时看日志里的 `xxx failed: HTTPError (HTTP 404)` 即可区分"上游挂了"和"真没数据"。
