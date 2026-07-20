# Step 3 技术文档：PostgreSQL、Redis与Checkpoint持久化

## 1. 步骤状态

- 开始时间：2026-07-16 14:19:50 +08:00（北京时间）
- 代码完成时间：2026-07-16 14:27:59 +08:00（北京时间）
- 首轮完整验收时间：2026-07-16 14:28:25 +08:00（北京时间）
- 最终验收时间：2026-07-16 14:33:14 +08:00（北京时间）
- GitHub发布时间：2026-07-16 14:33:57 +08:00（北京时间）
- 当前状态：完成并发布至GitHub草稿PR
- 当前置信度：96%
- 核心提交：`6019703`（Python原生持久化基础设施）
- 草稿PR：`https://github.com/Aqua2580/myagent/pull/1`

## 2. 本步骤目标

本步骤建立Python平台自己的持久化边界，不读取Java数据库表或Java状态格式：

1. PostgreSQL保存线程、Run摘要和不可变Checkpoint历史，是持久化事实源。
2. Redis保存活跃线程的最新Checkpoint，是带TTL的热状态缓存。
3. SQLAlchemy 2.0异步会话统一数据库访问方式。
4. Alembic独立管理Python Schema，支持升级和回滚。
5. Native与LangGraph引擎共享平台Checkpoint，不各自复制权限、审计和恢复逻辑。

## 3. 子步骤完成时间

| 子步骤 | 完成时间（北京时间） | 交付物 |
|---|---|---|
| PostgreSQL/Redis技术选型与依赖锁定 | 2026-07-16 14:20:31 +08:00 | `pyproject.toml`、`uv.lock`、配置项 |
| SQLAlchemy实体与异步会话 | 2026-07-16 14:27:46 +08:00 | `persistence/models.py`、`persistence/database.py` |
| SQL冷归档与Redis热缓存 | 2026-07-16 14:27:46 +08:00 | `persistence/checkpoint.py` |
| Alembic初始Schema | 2026-07-16 14:27:59 +08:00 | `alembic.ini`、`alembic/` |
| SQLite、PostgreSQL离线SQL与FakeRedis测试 | 2026-07-16 14:33:14 +08:00 | 22项测试与Alembic Schema漂移检查通过 |

## 4. 技术选型

### 4.1 已锁定的依赖版本

`uv.lock`当前解析结果：

- SQLAlchemy 2.0.51：异步ORM、事务与类型化实体。
- asyncpg 0.31.0：PostgreSQL异步驱动。
- Alembic 1.18.5：Schema版本管理。
- redis 6.4.0：`redis.asyncio`客户端和乐观事务。
- aiosqlite 0.22.1：本地快速数据库测试。
- fakeredis 2.36.2：不依赖外部Redis的行为测试。

### 4.2 为什么选择PostgreSQL

- UUID和带时区时间类型可直接表达Agent运行标识和时间线。
- Checkpoint使用JSONB，后续可以针对审计字段增加GIN或表达式索引。
- 行锁和唯一约束适合实现Checkpoint乐观并发控制。
- asyncpg与SQLAlchemy异步栈成熟，适合FastAPI并发模型。

SQLite只用于自动化测试，不作为生产数据库。模型使用SQLAlchemy通用类型加PostgreSQL类型变体：SQLite编译为JSON，PostgreSQL编译为JSONB。

## 5. 配置项

所有配置使用`MYAGENT_`前缀，数据库和Redis连接串使用Pydantic `SecretStr`，配置对象的`repr`不会打印实际连接串。

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `MYAGENT_DATABASE_URL` | `postgresql+asyncpg://localhost:5432/myagent` | 异步数据库连接串 |
| `MYAGENT_DATABASE_ECHO` | `false` | 是否打印SQL，生产环境应保持关闭 |
| `MYAGENT_DATABASE_POOL_SIZE` | `10` | 常驻连接池大小 |
| `MYAGENT_DATABASE_MAX_OVERFLOW` | `20` | 突发额外连接数 |
| `MYAGENT_REDIS_URL` | `redis://localhost:6379/0` | Redis异步连接串 |
| `MYAGENT_CHECKPOINT_KEY_PREFIX` | `myagent:checkpoint:v1` | Redis命名空间和格式版本 |
| `MYAGENT_CHECKPOINT_TTL_SECONDS` | `86400` | 热状态TTL，默认24小时 |

`.env.example`只包含无凭据的本地地址，真实用户名、密码、证书和云端地址只能通过本地`.env`或部署平台密钥注入。

## 6. 数据模型

### 6.1 `agent_threads`

保存线程身份和当前摘要：

- `thread_id`：UUID主键。
- `user_id`：业务用户标识。
- `status`：当前Agent状态。
- `current_checkpoint_version`：当前持久化版本，初始为0。
- `total_step_count`：线程累计执行步数。
- `created_at`、`updated_at`：带时区时间。
- `(user_id, updated_at)`联合索引用于用户会话列表。

### 6.2 `agent_runs`

保存一次执行的引擎选择和结果摘要：

- `run_id`：UUID主键。
- `thread_id`：关联线程，删除线程时级联清理。
- `engine`：只允许`native`或`langgraph`。
- `status`：本次Run状态。
- `request_payload`、`result_payload`：PostgreSQL使用JSONB。
- `error_message`：失败摘要，不应写入密钥或完整敏感上下文。
- `started_at`、`finished_at`：Run时间线。

一个Run开始后引擎值保持不变，继续遵守TaskRouter“单次Run不切换引擎”的约束。

### 6.3 `agent_checkpoints`

保存追加式状态快照：

- `checkpoint_id`：UUID主键。
- `thread_id`：关联线程。
- `version`：线程内单调递增版本。
- `state_schema_version`：Pydantic状态Schema版本。
- `state_payload`：完整Python原生ThreadState，PostgreSQL使用JSONB。
- `created_at`：快照写入时间。
- `(thread_id, version)`唯一约束阻止同版本重复写入。

历史Checkpoint只追加、不原地覆盖，便于故障恢复、审计和后续回放。

## 7. Checkpoint读写语义

### 7.1 写入

1. 调用方提交`ThreadState`和可选`expected_version`。
2. `SqlCheckpointStore`对状态进行深拷贝，避免调用方后续修改污染已返回的快照。
3. PostgreSQL事务锁定线程摘要，比较当前版本和`expected_version`。
4. 版本不一致时抛出`CheckpointConflictError`，不覆盖其他并发请求的状态。
5. 事务内追加Checkpoint并更新线程摘要。
6. 数据库提交成功后，`Checkpointer`刷新Redis热缓存。
7. Redis不可用时记录警告，但不回滚已经持久化的数据库事实。

### 7.2 读取

- `load_hot()`：优先读取Redis；未命中或Redis故障时回源SQL，并尝试回填Redis。适合活跃Agent执行。
- `load_durable()`：绕过Redis，直接读取SQL最新版本。适合恢复、审计和一致性敏感操作。

### 7.3 Redis并发与损坏处理

- Redis值是`CheckpointEnvelope` JSON，包含`version`、`state`和`saved_at`。
- `WATCH/MULTI/EXEC`保证旧版本不能覆盖新版本。
- 每个Key带TTL，避免无限保存非活跃线程。
- 无法通过Pydantic校验的缓存值会被删除，然后由SQL重新加载。

### 7.4 一致性边界

PostgreSQL是持久化事实源，Redis是最终一致的热缓存。两个存储之间不使用分布式事务：

- SQL失败：整个保存失败，不刷新Redis。
- SQL成功、Redis失败：保存仍成功，后续可通过`load_durable()`恢复。
- 审计和人工恢复必须调用`load_durable()`。
- 活跃执行可调用`load_hot()`获得低延迟状态。

## 8. Alembic操作

在`myagent-python/`目录执行：

```powershell
$env:UV_CACHE_DIR='.uv-cache'
$env:MYAGENT_DATABASE_URL='postgresql+asyncpg://user:password@host:5432/myagent'
uv run alembic upgrade head
```

查看当前版本：

```powershell
uv run alembic current
```

回滚本步骤Schema：

```powershell
uv run alembic downgrade base
```

生产回滚前必须先备份。降级会删除三张Python表及其中数据，不能作为日常故障恢复手段。

## 9. 自动化验证

已覆盖：

- SQL Checkpoint首次保存、版本递增、完整往返和删除。
- 过期`expected_version`触发并发冲突。
- 状态深拷贝，旧Envelope不会被后续运行修改。
- Redis只接受更新版本并设置TTL。
- Redis损坏数据自动丢弃。
- Redis未命中时SQL回源和Redis回填。
- Redis刷新失败时SQL持久化结果仍然可恢复。
- SQLite执行Alembic `upgrade head`和`downgrade base`。
- Alembic `check`确认ORM Metadata与首版迁移没有Schema漂移。
- PostgreSQL离线迁移SQL成功生成，并包含UUID和JSONB。
- 连接串在Settings输出中保持隐藏。
- pytest、Ruff和mypy严格模式。
- `uv lock --check`和高置信度敏感凭据扫描。

## 10. 当前限制与上线前动作

Docker Compose配置、随机密钥和本地应用连接配置已经建立，但当前机器没有安装Docker Desktop，因此本步骤仍未执行真实服务集成测试。现有测试已验证SQLAlchemy事务逻辑、迁移升级/回滚、PostgreSQL方言SQL编译、Redis协议行为和Compose语义，但上线前仍必须增加：

1. 对目标PostgreSQL版本执行真实`alembic upgrade head`和回滚演练。
2. 对目标Redis执行连接、认证、TLS、TTL和故障恢复测试。
3. 根据部署副本数调整连接池，确保`副本数 × (pool_size + max_overflow)`不超过数据库连接上限。
4. 通过云密钥服务或部署平台注入真实连接串。
5. 增加定期备份、Checkpoint保留周期和历史清理任务。

本地随机密钥已经安全生成，用户不需要提供密钥。下一步需要用户安装Docker Desktop；安装后即可启动隔离的PostgreSQL和Redis并完成真实集成验收。具体见`docs/STEP_03_1_DOCKER_INFRASTRUCTURE.md`。

## 11. 本步骤文件

- 配置与依赖：`.env.example`、`pyproject.toml`、`uv.lock`、`src/myagent/config.py`
- 数据层：`src/myagent/persistence/database.py`、`models.py`、`checkpoint.py`
- Schema：`alembic.ini`、`alembic/env.py`、`alembic/versions/20260716_01_initial_python_schema.py`
- 测试：`tests/test_config.py`、`tests/test_persistence.py`
- 架构与日志：`docs/ARCHITECTURE.md`、`docs/MIGRATION_LOG.md`
