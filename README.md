# MyAgent

本仓库发布MyAgent的Python迁移版本。本地工作区同时保留Java基线用于迁移参照，但Java目录被Git整体忽略，不会上传。

```text
myagent/
├── myagent-java/    # 仅本地存在，已被Git忽略
└── myagent-python/  # Python双引擎实现
```

Python版本采用自研`NativeAgentEngine`与`LangGraphAgentEngine`双引擎架构。迁移过程、验证证据和后续步骤记录在`myagent-python/docs/MIGRATION_LOG.md`。

## 安全说明

- 原Java项目中的本地`.env`不会进入Git。
- Python本地虚拟环境、下载工具和缓存不会进入Git。
- 提交前必须执行Secret扫描并核对暂存文件范围。
