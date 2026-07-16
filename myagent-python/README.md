# MyAgent Python

MyAgent 的 Python 迁移版本。该子项目与现有 Java 项目隔离开发，不修改原有源文件。

目标架构包含两个执行引擎：

- `NativeAgentEngine`：承载普通聊天、RAG、工具调用和简单子 Agent。
- `LangGraphAgentEngine`：承载深度研究、并行多 Agent 和复杂可恢复工作流。

两种引擎将共享模型网关、工具注册、安全策略、记忆、RAG、审计和 SSE 协议。

## 当前进度

已完成第一步工程骨架：

- FastAPI 应用工厂
- 类型安全的基础配置
- `/health/live` 和 `/health/ready`
- 基础自动化测试与静态检查配置
- 持续更新的迁移日志

详细记录见 [迁移日志](docs/MIGRATION_LOG.md)。

## 本地运行

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv sync
uv run uvicorn myagent.main:app --reload
```

访问：

- `http://localhost:8000/health/live`
- `http://localhost:8000/health/ready`
- `http://localhost:8000/docs`

## 验证

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv run pytest
uv run ruff check .
uv run mypy
```

## 安全约定

- 真实密钥不得写入仓库。
- 本地配置放入 `.env`，仓库只保留 `.env.example`。
- Python 代码只能位于本子项目目录，迁移期间不修改原 Java 源文件。

