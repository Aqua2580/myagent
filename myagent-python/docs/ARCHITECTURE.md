# Python 目标架构

## 设计边界

Python 版本采用双引擎，但只有一套平台能力：

```text
FastAPI / SSE
    -> TaskRouter
       -> NativeAgentEngine
       -> LangGraphAgentEngine

两种引擎共享：
Model Gateway / Tool Registry / Guardrail / RAG / Memory / Audit
```

`TaskRouter` 是执行策略路由器，不等同于普通业务意图分类。它使用“显式模式优先、规则评分其次、结构化模型分类兜底”的策略，决定当前 Run 使用 Native 或 LangGraph。一个 Run 启动后不允许中途切换引擎。

## 状态边界

- 平台 `RunState` 是API、审计和恢复使用的主状态。
- Native引擎直接操作平台状态。
- LangGraph只保存工作流内部节点状态，并通过引用挂接到平台RunState。
- 工具、安全、权限和数据访问不能被LangGraph节点绕过。

### Python原生状态约定

- 所有模型使用Pydantic严格校验和snake_case字段，不提供Java命名别名。
- thread_id使用UUID，时间使用带时区datetime，状态枚举序列化为小写字符串。
- 工具参数和结果直接保存结构化JSON，不在领域层传递JSON字符串。
- Token字段采用input_tokens、output_tokens和total_tokens，便于对接LangChain/LangGraph使用元数据。
- run_step_count与total_step_count均为正式字段，分别表达本次Run和Thread累计步数。
- 未知状态字段直接拒绝，Schema演进通过显式schema_version和迁移函数完成。

## 项目边界

- Python版拥有独立的REST、SSE、状态和数据Schema，不读取Java ThreadState。
- 可选择复用MySQL、Redis、Milvus和Elasticsearch基础设施，但使用独立命名空间和迁移版本。
- Java目录只作为本地业务参考，不参与构建、测试、提交或运行。

