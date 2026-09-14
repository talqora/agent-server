# Python 重写联调踩坑记录（Pulsar 超时 / venv 路径 / 镜像源等）

> 重写期间在本地全链路联调(真实 PG/Redis/Pulsar/Milvus)与镜像构建中实际踩到的坑。
> 每条都是"现象 → 根因 → 修复"，供后续排障对照。

---

## 1. Pulsar `receive(timeout)` 超时是**抛异常**，不是返回 None

- **现象**：worker 启动后显示消费正常，但消息永远不被处理；consumer 统计里 `TimeOut: 1`（只轮询了一次）。
- **根因**：`pulsar-client` 的 `Consumer.receive(timeout_millis)` 在超时无消息时抛 `pulsar.Timeout` 异常；
  消费循环把它当致命错误抛出 → `run_forever` 任务**静默死亡**（任务异常没人 await，被吞掉），
  consumer 连接还挂着，消息被路由到"假活"的消费者。
- **修复**（`agent_core/queue.py`）：`pulsar.Timeout` 视为空轮询 `continue`；其他异常记日志退避重试；
  另在 worker 入口给消费任务挂 `add_done_callback`，**消费循环异常必须可见**（否则又变静默死亡）。

## 2. 僵尸 worker 占着 Shared 订阅 → 消息被路由到不消费的实例

- **现象**：E2E 卡在摄取进度（上传成功但 worker 不处理）；`pgrep` 发现**两个** worker 实例。
- **根因**：本地反复重启调试时旧 worker 没被清干净（`pkill` 模式没匹配到 `uv run rag-worker` 的实际进程名）；
  Pulsar Shared 订阅把消息轮询分给两个消费者，一半落到"消费循环已死"的旧实例上。
- **修复**：`pkill -f rag-worker` 确认清空后再起新实例；排查"worker 不消费"时**先看有几个实例**。

## 3. Alembic：`CREATE SCHEMA` 混进迁移事务 → 连接关闭时整批 DDL 被回滚

- **现象**：`alembic upgrade head` 显示成功，但库里**一张表都没有**（连 `alembic_version` 都没）。
- **根因**：env.py 里先 `connection.execute(CREATE SCHEMA ...)` 再 `context.begin_transaction()`——
  该语句开了隐式事务，迁移结束时连接关闭触发**隐式回滚**，整批 DDL 全部丢弃。
- **修复**（`alembic/env.py`）：schema 创建用**独立连接 + `engine.begin()` 显式提交**，迁移走官方标准流程。

## 4. Docker 两阶段 venv 路径不一致 → "alembic: not found"

- **现象**：镜像构建成功、`/app/.venv/bin/alembic` 明明存在，容器启动却报 `sh: 1: alembic: not found`。
- **根因**：venv 内 console script 的 shebang 写死绝对路径（`#!/build/.venv/bin/python`）；
  镜像里 venv 被拷到 `/app/.venv`，shebang 指向的解释器不存在 → 内核报 "not found"。
- **修复**（`apps/rag-server/Dockerfile`）：构建阶段 `WORKDIR /app` 与运行阶段**同路径**，venv 直接拷 `/app/.venv`。

## 5. minio 官方镜像已从 Docker Hub 迁到 quay.io

- **现象**：`docker pull minio/minio:RELEASE.2024-12-18T13-15-44Z` → `pull access denied ... repository does not exist`。
- **根因**：MinIO 官方停止在 Docker Hub 发布，迁到 `quay.io/minio/minio`。
- **修复**：从 quay 拉取后本地 `docker tag` 回 compose 使用的名字（compose 文件保持不动）；
  生产 compose 本来就用 COS、不含 minio，不受影响。

## 6. pymilvus `MilvusClient` 的三个 API 细节

- **URI 需要 scheme**：`MilvusClient(uri="localhost:19530")` 报 `uri ... is illegal`——
  需 `http://localhost:19530`（已兼容 Node 版 `host:port` 写法：无 scheme 自动补 `http://`）。
- **`IndexParams` 不在顶层导出**：`from pymilvus import IndexParams` 报 ImportError；
  实际在 `pymilvus.milvus_client.index`。
- **load 状态是枚举**：`get_load_state()` 返回 `{"state": <LoadState.Loaded: 3>}`，
  判断要 `"Loaded" in str(value)`（不能用 `endswith("Loaded")`）。

## 7. colima 下 docker CLI 报凭据错误（Docker Desktop 残留）

- **现象**：`docker pull` 报 `error getting credentials - err: exec: "docker-credential-desktop": executable file not found`。
- **根因**：`~/.docker/config.json` 残留 `"credsStore": "desktop"`（Docker Desktop 的凭据助手已不存在）。
- **修复**（二选一）：① 删掉 `~/.docker/config.json` 里的 `credsStore` 字段（一劳永逸，推荐）；
  ② 临时：`DOCKER_CONFIG` 指向一个干净的配置目录（注意该目录也影响 CLI 插件发现，需链接 `cli-plugins`）。

## 8. FastAPI 联合返回类型需显式 `response_model=None`

- **现象**：`async def f() -> JSONResponse | StreamingResponse` 定义路由时直接抛
  `FastAPIError: Invalid args for response field`。
- **修复**：路由装饰器加 `response_model=None`（联合 Response 类型无法推断响应模型）。
