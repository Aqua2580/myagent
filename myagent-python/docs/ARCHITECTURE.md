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

## 兼容目标

- 保留现有REST与SSE事件语义。
- 能读取Java版ThreadState JSON。
- 复用现有MySQL、Redis、Milvus和Elasticsearch数据。
- Java与Python迁移期间不能同时执行同一个Thread。

