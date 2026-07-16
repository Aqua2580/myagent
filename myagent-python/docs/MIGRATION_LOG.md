# MyAgent Python 迁移日志

本文档在每个迁移步骤完成后更新。每一步必须记录范围、文件、验证结果、遗留风险和下一步入口。

## Step 1：Python工程骨架

- 日期：2026-07-16
- 状态：完成并发布至GitHub草稿PR
- 置信度：96%

### 完成内容

- 创建独立目录 `myagent-python/`，未修改现有Java源文件。
- 建立Python 3.12、uv和`src`布局。
- 建立FastAPI应用工厂。
- 实现`/health/live`和`/health/ready`。
- 建立Pydantic Settings基础配置，不包含真实密钥。
- 配置pytest、Ruff和mypy。
- 编写配置、健康检查和OpenAPI测试。
- 记录双引擎目标架构和状态边界。

### 新增文件

- 项目与环境：`pyproject.toml`、`.python-version`、`.env.example`、`.gitignore`
- 应用代码：`src/myagent/`
- 测试：`tests/`
- 文档：`README.md`、`docs/ARCHITECTURE.md`、`docs/MIGRATION_LOG.md`

### 验证清单

- [x] `uv sync`：使用CPython 3.12.13，成功解析并安装依赖
- [x] `uv run pytest`：5项测试全部通过
- [x] `uv run ruff check .`：全部通过
- [x] `uv run mypy`：严格模式通过，5个源文件无问题
- [x] 确认原项目除新增目录外没有产生新的变更
- [x] 发布到`Aqua2580/myagent`

### 验证说明

- FastAPI TestClient产生一条上游Starlette弃用提示，不影响当前测试结果；后续升级HTTP测试适配器时处理。
- 首次验证发现包缺少PEP 561类型标记，已增加`src/myagent/py.typed`并重新通过mypy。
- uv的Python安装目录和缓存均限制在本子项目内，不写入原项目源代码。

### 发布说明

- 系统级GitHub CLI自动安装未成功，已改为在`.tools/`安装官方便携版GitHub CLI 2.94.0；该目录已被Git忽略。
- 已确认GitHub CLI账户`Aqua2580`认证有效，Step 1已发布到草稿PR #1。

### 下一步

Step 2建立Python原生领域模型和状态Fixture，包括AgentStatus、ChatMessage、ToolCall、TokenUsage与ThreadState。

## Step 2：Python原生领域模型与状态Fixture

- 日期：2026-07-16
- 状态：完成、通过自动化验证并发布至GitHub草稿PR
- 置信度：97%

### 决策变更

- 用户明确要求停止Java适配，将项目设计为完全符合Python生态的独立实现。
- 提交`58a516a`中的Java兼容模型由本次重构取代，不再作为后续接口约束。

### 完成内容

- 全部领域字段改为snake_case，枚举值改为小写。
- thread_id改为UUID，所有状态时间强制包含时区。
- 工具参数和结果改为结构化JSON对象。
- Token字段改为input_tokens、output_tokens和total_tokens。
- run_step_count与total_step_count改为正式顶层字段。
- Pydantic配置改为extra=forbid，未知状态必须通过显式Schema迁移处理。
- 增加cancelled状态，为asyncio任务取消和LangGraph工作流取消预留语义。
- Fixture改为Python原生COMPLETED与WAITING_CONFIRMATION状态。

### 验证清单

- [x] Python原生状态读取与往返
- [x] UUID、带时区datetime和小写枚举
- [x] 结构化Tool Call与Tool Result
- [x] 未知字段拒绝
- [x] 消息Role载荷约束
- [x] run与total步数分离
- [x] pytest：15项全部通过
- [x] Ruff：全部通过
- [x] mypy：严格模式通过，7个源文件无问题
- [x] 新增内容高置信度敏感密钥模式扫描命中0个
- [x] 更新GitHub草稿PR，核心提交`2d1f264`

### 验证说明

- 两组Python原生Fixture覆盖完成态、等待确认态、工具调用、工具结果、审计记录和Token统计。
- 序列化专项测试确认输出只使用snake_case字段和小写枚举，并可恢复UUID与带时区datetime。
- FastAPI TestClient仍有一条已记录的上游Starlette弃用提示，与领域模型无关，不影响测试通过。

### 发布结果

- 分支：`agent/python-initial-scaffold`
- 核心提交：`2d1f264`（Python原生运行状态模型）
- 草稿PR：`https://github.com/Aqua2580/myagent/pull/1`

### 下一步

Step 3将建立Python原生SQLAlchemy实体、Redis Checkpointer与独立Alembic Schema。

## Repository Step：双目录重组

- 日期：2026-07-16
- 状态：完成并发布至GitHub草稿PR
- 置信度：97%

### 完成内容

- 新建`myagent-java/`，将原Java项目的24个顶层条目原样移入。
- 保留`myagent-python/`作为独立Python迁移目录。
- 删除不再使用的原Java仓库`.git`元数据，准备初始化新的Aqua仓库。
- 在仓库根目录增加安全忽略规则，阻止`.env`、构建产物、运行数据、Python环境和本地工具上传。
- 增加根目录README，明确Java/Python双目录结构。

### 说明

- 根目录中的`.agents/`是Codex工作区托管元数据，受系统保护，不能移动；它已被根级`.gitignore`排除，不属于项目内容，也不会上传GitHub。
- Java源码内容未编辑，本步骤只改变目录位置。

### 验证清单

- [x] 原Java项目入口`pom.xml`位于`myagent-java/`
- [x] Java主源码位于`myagent-java/src/main/java/`
- [x] Python项目位于`myagent-python/`
- [x] 根级规则忽略Java`.env`和双方构建环境
- [x] 初始化新Git仓库并绑定`Aqua2580/myagent`
- [x] 提交候选文件共446个，敏感密钥模式扫描命中0个
- [x] 完成GitHub CLI认证、提交和推送

### 当前发布阻塞

- 已在正常联网环境确认GitHub CLI登录有效，账户为`Aqua2580`，具备`repo`和`workflow`权限。
- 此前的“Token invalid”是受限执行环境将API请求导向不可用代理`127.0.0.1:9`产生的误报，不是Token实际失效。
- GitHub认证阻塞已解除。

### 发布结果

- 分支：`agent/python-initial-scaffold`
- 基线提交：`6a695e9`（Python工程骨架）
- 文档提交：`512869c`（Python-only仓库范围）
- 草稿PR：`https://github.com/Aqua2580/myagent/pull/1`
- 远端`main`未被覆盖，Python改动通过草稿PR进入评审流程。

## Repository Step：忽略Java基线目录

- 日期：2026-07-16
- 状态：完成
- 置信度：99%

### 完成内容

- 在根级`.gitignore`中加入`myagent-java/`。
- Java版本继续保留在本地作为迁移参照，但不进入新仓库、不参与提交，也不会上传到GitHub。

### 验证清单

- [x] `git check-ignore myagent-java/pom.xml`命中根级忽略规则
- [x] `git status`不再列出`myagent-java/`
