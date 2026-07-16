# MyAgent Python

MyAgent 是面向Python生态重新设计的Agent平台，不承担Java接口、状态或数据结构兼容责任。Java目录仅保留在本地作为业务参考，Python项目独立开发和演进。

目标架构包含两个执行引擎：

- `NativeAgentEngine`：承载普通聊天、RAG、工具调用和简单子 Agent。
- `LangGraphAgentEngine`：承载深度研究、并行多 Agent 和复杂可恢复工作流。

两种引擎将共享模型网关、工具注册、安全策略、记忆、RAG、审计和 SSE 协议。

## 当前进度

已完成工程骨架、Python原生运行状态和持久化基础设施：

- FastAPI 应用工厂
- 类型安全的基础配置
- `/health/live` 和 `/health/ready`
- 基础自动化测试与静态检查配置
- Pydantic严格领域模型、Python原生状态Fixture与序列化约束
- PostgreSQL、SQLAlchemy异步会话和独立Alembic Schema
- Redis热状态缓存、SQL追加式Checkpoint与乐观版本控制
- 持续更新的迁移日志

详细记录见 [迁移日志](docs/MIGRATION_LOG.md)。

Step 3的表结构、一致性策略、迁移和故障处理见[持久化技术文档](docs/STEP_03_PERSISTENCE.md)。

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

## 数据库迁移

配置`MYAGENT_DATABASE_URL`后执行：

```powershell
uv run alembic upgrade head
```

默认生产技术栈是PostgreSQL + asyncpg + Redis asyncio。SQLite和FakeRedis只用于快速自动化测试。

## 安全约定

- 真实密钥不得写入仓库。
- 本地配置放入 `.env`，仓库只保留 `.env.example`。
- Python代码只能位于本子项目目录，不修改本地保留的Java源文件。

