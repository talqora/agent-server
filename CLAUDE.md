# agent-server — AI 工作入口

> 全局约束见 `~/.claude/CLAUDE.md`。本文件只给：定位 + 文档地图 + 跨服务约束 + 入口。
> 架构与计划在 `docs/` —— 开工前按需读，本文件不重复。

## 这是什么
AI 助手后端（与 our-chat IM 融合）。**Python 重写后**：
- `apps/rag-server/`（Python）：FastAPI + SQLAlchemy(async) + Alembic + Pulsar(任务队列) + Milvus(向量) +
  Redis(pub/sub 背板) + OpenAI 兼容 LLM；双角色同代码库：`rag-http`（HTTP/SSE）+ `rag-worker`（队列消费）。
- `packages/agent-core/`（Python 共享库）：auth / run-engine / queue / llm / vector / 配置日志 —— 新服务只依赖它。
- `apps/node-server/`：重写前 Node 版，**保留作对照、不再部署**。

分支 `feat/python-rewrite`。工作区为 uv workspace（根 `pyproject.toml`）。

## 文档地图（权威，勿在 CLAUDE.md 重复）
- 架构设计：`docs/架构设计/`（01 多服务评估 → 02 队列/实时评审 → 03 多服务架构与独立扩缩容 →
  04 重写路线图 → 05 契约生成与 FastAPI 整合）
- 重写决策（重写前）：`docs/技术方案/`（利弊分析 / 边界校验 / Web 框架选型 / 双进程架构 / 契约分发）
- 历史重构计划：`docs/项目重构方案/`（Node 时代）｜跨服务鉴权：`docs/跨服务鉴权方案/`（方案 D-JWKS）
- 部署 `docs/docker.md`｜排障 `docs/debug/`

## 跨服务约束
- **鉴权用 JWKS 验签**（PyJWT）：our-chat 是 IdP 签发 JWT，本服务用其公钥验签，**不自签发**（HS256 仅本地兜底）。
- **契约单一来源是 proto**：各端从 `proto/` 生成（TS：ts-proto；Python：betterproto2）；
  **生成物禁止手改**（`contracts/gen/`），改契约只改 proto + 重新生成。
- **多服务纪律**（docs/架构设计/03）：资源命名空间（PG schema / Pulsar topic / Redis 前缀 / Milvus collection）；
  **禁止跨服务读表**（协作走 API/事件）；身份锚点是 `(issuer, subject)` 而非本地 id。
- 重构分阶段推进（见 doc04），不砍既有功能。

## 常用命令（仓库根）
- `make dev`（中间件 + 迁移 + 双角色）｜`make llm-stub`（无 Ollama 时的协议级 stub）
- 质量门禁：`make lint`（ruff + mypy strict）｜`make test`（pytest）｜`make e2e`（全链路端到端）
