# MyAgent

本仓库用于并行保存MyAgent的Java基线版本和Python迁移版本。

```text
myagent/
├── myagent-java/    # 原Java项目，仅作为迁移参照和兼容基线
└── myagent-python/  # Python双引擎实现
```

Python版本采用自研`NativeAgentEngine`与`LangGraphAgentEngine`双引擎架构。迁移过程、验证证据和后续步骤记录在`myagent-python/docs/MIGRATION_LOG.md`。

## 安全说明

- 原Java项目中的本地`.env`不会进入Git。
- Python本地虚拟环境、下载工具和缓存不会进入Git。
- 提交前必须执行Secret扫描并核对暂存文件范围。
