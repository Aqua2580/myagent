# Step 3.1 技术文档：Docker基础设施

## 1. 当前状态

- 开始时间：2026-07-16 14:46:09 +08:00（北京时间）
- Compose代码完成时间：2026-07-16 14:49:59 +08:00（北京时间）
- 官方Compose语义验证时间：2026-07-16 14:52:41 +08:00（北京时间）
- 本地密钥与应用配置初始化时间：2026-07-16 14:54:18 +08:00（北京时间）
- 最终静态验收时间：2026-07-16 14:58:15 +08:00（北京时间）
- GitHub发布时间：2026-07-16 14:59:41 +08:00（北京时间）
- 配置状态：完成并发布，配置置信度98%
- 运行状态：等待安装Docker Desktop后启动并做真实服务验收
- 核心提交：`41e8671`（安全Docker基础设施服务）
- 草稿PR：`https://github.com/Aqua2580/myagent/pull/1`

本步骤先交付PostgreSQL和Redis基础设施。MyAgent应用镜像将在运行服务层接口稳定后加入，避免重复构建和过早固化尚未完成的启动流程。

## 2. 服务版本

镜像使用官方固定版本，不使用会漂移的`latest`：

| 服务 | 镜像 | 用途 |
|---|---|---|
| PostgreSQL | `postgres:18.4-alpine3.23` | Thread、Run和Checkpoint持久化事实源 |
| Redis | `redis:8.8.0-alpine3.23` | 活跃Thread最新Checkpoint热缓存 |

版本可以通过`docker/.env`覆盖，但升级前必须先查看数据库升级说明、备份数据并执行迁移演练。

Redis 8采用RSALv2、SSPLv1或AGPLv3多许可证模式。企业发布前应由法务根据实际分发和托管方式确认采用的许可；如企业政策不接受，可将实现替换为兼容Redis协议的服务，Python Checkpointer接口不需要变化。

## 3. 目录结构

```text
myagent-python/
├── compose.yaml
├── scripts/
│   └── setup_docker.ps1
└── docker/
    ├── .env.example
    └── secrets/
        ├── postgres_password.txt.example
        └── redis.conf.example
```

本地执行初始化后还会生成以下文件，它们全部被Git忽略：

- `.env`：Python应用本地连接配置。
- `docker/.env`：镜像版本、数据库名、用户名和本机端口。
- `docker/.env.app.generated`：可供已有`.env`手工合并的连接配置。
- `docker/secrets/postgres_password.txt`：PostgreSQL随机密码。
- `docker/secrets/redis.conf`：包含Redis随机密码的实际配置。

## 4. 安全设计

### 4.1 密钥

- `setup_docker.ps1`使用.NET `RandomNumberGenerator`分别生成256位随机PostgreSQL和Redis密码。
- 密码不会输出到终端，也不会写入Compose环境变量。
- PostgreSQL通过`POSTGRES_PASSWORD_FILE`读取Docker secret。
- Redis通过只挂载到容器内的`redis.conf`读取`requirepass`。
- 初始化脚本默认拒绝覆盖已有密钥；`-Force`必须显式指定。
- 数据卷已经存在时不要使用`-Force`随意更换密码，否则应用配置与服务内密码会失配。

Docker Compose本地secret本质是宿主机文件挂载，不等同于生产密钥管理系统。生产部署必须改用云密钥服务、Docker Swarm secret或Kubernetes Secret，并限制宿主机文件权限。

### 4.2 网络

- PostgreSQL只发布到`127.0.0.1:5432`。
- Redis只发布到`127.0.0.1:6379`。
- 两个容器位于`myagent-backend`内部网络。
- 没有Adminer、Redis Commander等额外管理端口。
- 需要远程访问时应通过VPN、SSH隧道或受控网关，不应把端口改成`0.0.0.0`直接暴露。

### 4.3 PostgreSQL

- 使用SCRAM-SHA-256主机认证。
- 首次初始化启用数据页校验和。
- PostgreSQL 18按官方目录变化设置`PGDATA=/var/lib/postgresql/18/docker`，命名卷挂载到`/var/lib/postgresql`。
- `shm_size`设置为128MB，避免常见共享内存不足问题。
- 健康检查使用`pg_isready`，不在命令行传递密码。

### 4.4 Redis

- 启用Protected Mode和密码认证。
- 启用AOF，`appendfsync everysec`。
- 同时保留低频RDB快照。
- 本地默认最大内存256MB，使用`allkeys-lru`；Redis只是热缓存，淘汰后可以从PostgreSQL恢复。
- 健康检查从挂载配置中读取密码，不把密码写入Compose文件。

### 4.5 数据和日志

- PostgreSQL使用命名卷`myagent-postgres-data`。
- Redis使用命名卷`myagent-redis-data`。
- 容器日志限制为每个文件10MB、最多3个文件。
- `docker compose down`保留数据卷。
- `docker compose down -v`会永久删除本地数据库和Redis数据，只能在明确需要重置时执行。

## 5. 首次启动

### 5.1 前置条件

Windows需要安装Docker Desktop，并启用Linux containers和WSL 2后端。安装完成后确认：

```powershell
docker version
docker compose version
```

### 5.2 初始化本地配置

在`myagent-python/`目录执行：

```powershell
.\scripts\setup_docker.ps1
```

当前工作区已经执行过本命令，密钥和`.env`已经生成。重复执行会安全失败，不会覆盖现有密钥。

### 5.3 启动服务

```powershell
docker compose --env-file docker/.env up -d
docker compose --env-file docker/.env ps
```

等待`postgres`和`redis`都显示`healthy`。

### 5.4 初始化数据库Schema

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv run alembic upgrade head
uv run alembic current
```

## 6. 运行验收命令

```powershell
docker compose --env-file docker/.env config --quiet
docker compose --env-file docker/.env ps
docker compose --env-file docker/.env exec postgres pg_isready -U myagent -d myagent
docker compose --env-file docker/.env exec redis sh -c 'REDISCLI_AUTH="$(awk ''$1 == "requirepass" {print $2}'' /run/secrets/redis_config)" redis-cli --no-auth-warning ping'
uv run alembic check
```

验收标准：

- 两个容器均为`healthy`。
- PostgreSQL输出`accepting connections`。
- Redis输出`PONG`。
- Alembic输出`No new upgrade operations detected`。
- Python Checkpointer真实保存、Redis命中、Redis清空后SQL回源均通过。

最后一项将在Docker Desktop可用后增加真实服务集成测试并记录运行完成时间。

## 7. 常用运维命令

查看日志：

```powershell
docker compose --env-file docker/.env logs -f --tail 100 postgres redis
```

停止并保留数据：

```powershell
docker compose --env-file docker/.env down
```

重新启动：

```powershell
docker compose --env-file docker/.env up -d
```

拉取当前固定标签的安全更新后重新创建：

```powershell
docker compose --env-file docker/.env pull
docker compose --env-file docker/.env up -d
```

固定标签不会自动升级版本。修改标签前必须先阅读发行说明和执行备份。

## 8. 当前验证结果

- YAML由PyYAML成功解析。
- 6项Docker配置测试通过。
- 项目完整pytest：28项全部通过。
- Ruff、mypy严格模式和`uv lock --check`全部通过。
- 官方Docker Compose 5.3.1二进制SHA256校验通过。
- `compose config --quiet`语义检查通过。
- 解析服务严格为`postgres`和`redis`。
- 解析镜像严格为固定的PostgreSQL 18.4与Redis 8.8版本。
- 随机密钥已生成且未输出。
- Python Settings成功读取本地连接配置，`repr`保持脱敏。
- 实际密钥文件经`git check-ignore`确认不会提交。
- 高置信度敏感凭据模式扫描命中0个。

## 9. 尚需用户完成

当前机器没有Docker命令和Docker daemon。请安装Docker Desktop；安装完成后告诉我，我会继续：

1. 启动PostgreSQL和Redis。
2. 等待两个服务健康。
3. 执行Alembic真实迁移。
4. 运行真实PostgreSQL/Redis Checkpointer集成测试。
5. 把真实运行验收时间和结果补入本文档及迁移日志。
