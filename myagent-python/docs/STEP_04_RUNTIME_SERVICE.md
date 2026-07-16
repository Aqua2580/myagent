# Step 4 技术文档：Thread与Run运行服务层

## 1. 步骤状态

- 开始时间：2026-07-16 15:42:58 +08:00（北京时间）
- 核心代码完成时间：2026-07-16 15:48:01 +08:00（北京时间）
- 行为测试完成时间：2026-07-16 15:49:30 +08:00（北京时间）
- Schema漂移检查加入时间：2026-07-16 15:50:16 +08:00（北京时间）
- 首轮完整验收时间：2026-07-16 15:50:37 +08:00（北京时间）
- 文档初稿完成时间：2026-07-16 15:51:57 +08:00（北京时间）
- 最终完整验收时间：2026-07-16 15:55:06 +08:00（北京时间）
- 当前状态：代码、文档与自动化验收完成，等待GitHub发布
- 当前置信度：97%

## 2. 本步骤目标

Step 4把Step 2的`ThreadState`和Step 3的`Checkpointer`组合成稳定的运行服务接口，使FastAPI、Native引擎和LangGraph适配器不需要直接操作数据库事务。

本步骤解决以下平台问题：

1. 新建或继续Thread时，统一创建Run并保存首个Checkpoint。
2. 一个Run启动后固定使用`native`或`langgraph`，后续保存不能切换。
3. Run状态和对应Checkpoint在同一SQL事务中更新。
4. 同一Thread任意时刻最多有一个活跃Run。
5. Checkpoint版本冲突、越权访问和非法状态转换返回明确异常。
6. 运行中断后可以通过`run_id`和持久化Checkpoint恢复上下文。

TaskRouter、模型调用、工具执行和LangGraph节点不属于本步骤。TaskRouter将在下一步选择引擎，然后把结果作为`StartRunCommand.engine`传入；运行服务只保证选择一旦落库就不可改变。

## 3. 组件结构

```text
FastAPI / TaskRouter / Engine Adapter
                 |
              RunService
                 |
         RuntimeRepository
          /              \
RunRecord lifecycle   SqlCheckpointStore
          \              /
           one SQL transaction
                    |
             committed envelope
                    |
          RedisCheckpointCache
             best-effort publish
```

### 3.1 `StartRunCommand`

启动入口使用严格Pydantic模型，包含：

- `user_id`：Thread所有者。
- `engine`：`native`或`langgraph`。
- `input_message`：本次用户输入，自动去除首尾空白并拒绝空字符串。
- `thread_id`：为空时创建新Thread，存在时继续已有Thread。
- `request_payload`：路由参数、模式或其他JSON原生请求元数据。

### 3.2 `RunSession`

引擎获得的运行上下文包含：

- 不可变的`run_id`和`engine`。
- 当前`checkpoint_version`。
- 与数据库隔离的`ThreadState`深拷贝。
- 带时区的`started_at`。

`RunSession`外层被冻结，防止误改Run身份。内部`ThreadState`允许引擎增加消息、工具审计、Token和步骤计数；每次保存返回新的`RunSession`和新版本号。

### 3.3 `RunService`

公开方法及职责：

| 方法 | 作用 | 允许的目标状态 |
|---|---|---|
| `start_run()` | 创建或继续Thread并启动Run | `running` |
| `save_progress()` | 保存运行中或等待确认状态 | `running`、`waiting_confirmation` |
| `complete_run()` | 正常或部分完成 | `completed`、`partial_completed` |
| `fail_run()` | 保存安全错误摘要并结束 | `error` |
| `cancel_run()` | 响应`asyncio`取消或用户取消 | `cancelled` |
| `resume_run()` | 从持久化状态恢复活跃Run | 仅活跃状态 |

## 4. Run生命周期

```text
                 +----------------------+
                 |                      v
running <-> waiting_confirmation    cancelled
   |             |                     ^
   +-------------+---------------------+
   |
   +--> completed
   +--> partial_completed
   +--> error
```

- `running`和`waiting_confirmation`是活跃状态，可以反复保存Checkpoint。
- 四个终态不可再次保存、完成或取消。
- `fail_run()`拒绝空错误，数据库最多保存4000字符的摘要；调用方仍必须避免传入密钥或完整敏感上下文。
- `resume_run()`只恢复活跃Run，终态只用于查询、审计或新建下一Run。

## 5. SQL事务与Redis边界

### 5.1 开始Run

1. `RunService`加载 durable Checkpoint，或创建新的`ThreadState`。
2. 校验`user_id`所有权。
3. 重置`run_step_count`并追加用户消息。
4. `RuntimeRepository`在同一SQL事务中追加Checkpoint和插入`RunRecord`。
5. SQL提交成功后才把`CheckpointEnvelope`发布到Redis。

如果Run插入、状态约束或Checkpoint版本检查失败，整个SQL事务回滚，不会留下只有Run没有Checkpoint、或只有Checkpoint没有Run的半完成状态。

### 5.2 保存和结束Run

1. 使用`SELECT ... FOR UPDATE`锁定Run。
2. 校验Run仍处于活跃状态。
3. 校验`thread_id`、固定`engine`和`expected_version`。
4. 在同一事务中追加Checkpoint并更新Run状态、结果、错误或结束时间。
5. SQL提交后刷新Redis；Redis故障不会撤销数据库事实。

PostgreSQL仍是事实源，Redis只负责热状态加速。恢复和审计继续使用`load_durable()`。

## 6. 并发与安全约束

### 6.1 单Thread单活跃Run

应用层在持有Thread行锁后检查活跃Run，数据库层额外增加部分唯一索引：

```sql
CREATE UNIQUE INDEX uq_agent_runs_thread_active
ON agent_runs (thread_id)
WHERE status IN ('running', 'waiting_confirmation');
```

即使未来出现绕过服务层的错误代码，数据库也会阻止同一Thread同时存在两个活跃Run。终态Run不占用该唯一位置，因此同一Thread可以顺序启动多次Run。

### 6.2 引擎固定

- 引擎只在`start_run()`时写入`agent_runs.engine`。
- `save_progress()`和所有终态方法不接收新的引擎选择。
- Repository仍会比较`RunSession.engine`与数据库值，伪造或过期上下文触发`RunEngineMismatchError`。
- Native与LangGraph不能在同一个Run中相互接管；若需要改用另一引擎，必须先结束当前Run并新建Run。

### 6.3 所有权与版本

- 继续或恢复Thread必须匹配持久化`user_id`。
- `SqlCheckpointStore`禁止现有Thread的`user_id`被Checkpoint改写。
- 每次写入携带`expected_version`；旧RunSession再次保存触发`CheckpointConflictError`。
- Run与State的`thread_id`不一致时触发`RunStateMismatchError`。

这些异常是服务层错误，不包含数据库连接串、Redis密码或请求密钥。

## 7. Schema迁移

新增Alembic修订`20260716_02`：

- 为`agent_runs.status`增加已知状态Check Constraint。
- 为活跃Run增加跨PostgreSQL和SQLite测试方言的部分唯一索引。
- SQLite迁移使用Alembic batch table模式，支持自动化升级和回滚。
- PostgreSQL离线SQL可生成原生Check Constraint和`WHERE`部分索引。

Docker真实PostgreSQL迁移仍属于暂缓的Step 3.1运行门禁；当前已通过SQLite执行迁移和PostgreSQL离线SQL编译。

## 8. 自动化验证

新增行为覆盖：

- 新Thread启动、运行中保存、等待确认、恢复和完成。
- Run外层身份固定、ThreadState快照可独立修改。
- 同一Thread第二个活跃Run被拒绝，取消后可启动下一Run。
- 固定引擎不可切换。
- 过期Checkpoint版本不能覆盖新状态。
- Thread启动、恢复和Checkpoint写入的所有权保护。
- 空错误拒绝、终态不可二次结束。
- Redis热状态与SQL durable状态一致。
- Alembic升级、回滚和ORM Schema漂移检查。

最终完整结果：

- pytest：33项通过，1条已知Starlette上游弃用提示。
- Ruff：通过。
- mypy严格模式：16个源文件通过。
- `uv lock --check`：通过。
- PostgreSQL离线迁移SQL包含Run状态约束和活跃Run部分唯一索引。

## 9. 文件清单

- 运行服务：`src/myagent/runtime/models.py`、`repository.py`、`service.py`、`errors.py`
- 持久化事务复用：`src/myagent/persistence/checkpoint.py`
- ORM约束：`src/myagent/persistence/models.py`
- Alembic：`alembic/versions/20260716_02_run_lifecycle_guards.py`
- 测试：`tests/test_runtime_service.py`、`tests/test_persistence.py`
- 文档：`docs/ARCHITECTURE.md`、`docs/MIGRATION_LOG.md`、本文档

## 10. 当前限制与下一步

- Docker真实PostgreSQL/Redis验收尚未完成，不能把SQLite结果等同于生产环境验证。
- 本步骤没有实现HTTP Run API或SSE；FastAPI装配将在路由与引擎协议稳定后完成。
- 本步骤没有实现TaskRouter，也没有调用LLM做意图识别。
- 本步骤没有安装LangGraph依赖；只有复杂工作流适配器进入开发时才锁定版本。

下一步是Step 5：实现可解释的TaskRouter和统一Engine Protocol。路由采用显式模式优先、确定性规则评分其次、结构化模型分类兜底，并把每次选择理由写入可审计结果；Run启动后仍由本步骤保证引擎不变。
