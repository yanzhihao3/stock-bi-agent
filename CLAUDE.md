# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Stock BI Agent

智能股票查询与分析系统，基于 FastMCP + FastAPI + Streamlit 构建。

## 技术架构

```
用户浏览器 (Streamlit / API)
       │
       ▼
FastAPI 后端 (端口 8000)
  ├── routers/     API 路由
  ├── services/    业务逻辑
  ├── models/      数据模型
  └── /stock       股票 API
       │
       ▼ (MCP 工具调用)
MCP 服务聚合器 (main_mcp.py, 端口 8900)
  ├── autostock.py  股票数据 (autostock.cn API)
  ├── news.py       新闻服务 (whyta.cn API)
  ├── saying.py     名言服务 (whyta.cn API)
  └── tool.py       实用工具 (whyta.cn API)
```

## 核心模块

### MCP 工具服务 (`api/`)
- `autostock.py` - 股票数据查询（K线、排名、板块等），Token: `zgaLG8unUPr`，API 文档: https://s.apifox.cn/c3278b4f-5629-4732-858c-36758ff5d083/api-147275957
- `news.py` - 今日要闻、抖音热点、GitHub热榜等，Token: `6d997a997fbf`，API 文档: https://apis.whyta.cn/
- `saying.py` - 名言鸡汤服务，Token: `6d997a997fbf`
- `tool.py` - 城市天气、电话归属地、汇率换算等，Token: `6d997a997fbf`

### MCP 聚合 (`main_mcp.py`)
- 通过 `FastMCP.from_fastapi()` 将 FastAPI 应用转为 MCP 服务器
- 使用 `mcp.import_server()` 合并多个 MCP 服务（news, saying, tool）
- 对外暴露统一 MCP 接口，AI 无需知道工具来源
- SSE 传输协议，端口 8900

### AI 对话核心 (`services/chat.py`)
- 使用 `agents` 包（OpenAI Chat Completions 风格）
- `MCPServerSse` 连接 MCP 服务，通过 `ToolFilterStatic` 按任务类型过滤工具
- `AdvancedSQLiteSession` 存储 Agent 对话状态
- 流式输出：`Runner.run_streamed()` + `ResponseTextDeltaEvent`
- 工具分类：`TOOL_CATEGORIES` 定义了股票分析、新闻聚合、通用工具、名言鸡汤四类
- 任务映射：`TASK_TO_CATEGORIES` 根据任务类型自动推荐工具分类

### Agent 模块 (`agent/`)
- `stock_agent.py` - 股票分析 Agent（目前主要为占位实现）
- `csv_agent.py` - CSV 文件问答
- `excel_agent.py` - Excel 文件问答
- `summary_agent.py` - 论文总结
- `vison_agent.py` - 多模态图片问答
- `db_agent.py` - 数据库问答（nl2sql，代码注释掉了）

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

## 启动方式

```bash
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
```

## 测试

```bash
# 运行所有测试
pytest test/

# 运行单个测试文件
pytest test/test_mcp.py

# 运行特定测试
pytest test/test_agent.py::test_agent_runing -v
```

## 外部 API

### autostock.cn（股票数据）
- Token: `zgaLG8unUPr`（硬编码在 `api/autostock.py`）
- API 文档: https://s.apifox.cn/c3278b4f-5629-4732-858c-36758ff5d083/api-147275957
- 注册入口: https://www.autostock.cn

### whyta.cn（新闻/名言/工具）
- Token: `6d997a997fbf`（硬编码在 `api/news.py`, `api/saying.py`, `api/tool.py`）
- API 文档: https://apis.whyta.cn/

**注意**: Token 直接硬编码在代码中，如需更换新 token 直接修改对应文件开头的 `TOKEN` 变量。