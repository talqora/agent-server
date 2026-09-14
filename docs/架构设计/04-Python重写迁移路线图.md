# 04 · Python 重写迁移路线图

> 依据：01（评估）/ 02（队列与实时）/ 03（多服务架构与独立扩缩容）三份架构文档。
> 目标：`apps/node-server`（NestJS）→ **`apps/rag-server`（Python，功能全量对齐）** + `packages/agent-core`
> （共享库）+ 多服务基座（服务模板/命名空间/独立扩缩容）+ 部署与 CI 切换 + **本地全链路端到端验证**。
> 工作流：**契约先行 → 平台基座 → 领域模块 → 部署 → 验证**；每阶段自带测试与验收；
> 质量门禁（ruff / mypy strict / pytest / wire 格式对照）每阶段收口；发现偏差立即回改。

---

## 0. 决策快照（已定，不再逐条确认）

| # | 决策 | 值 |
|---|---|---|
| 1 | 队列 | **Pulsar 自建**（standalone；dev compose 与 prod 同构） |
| 2 | 目录 | `apps/rag-server/`（Python）；`apps/node-server/` 保留对照、不再部署 |
| 3 | 共享库 | `packages/agent-core`（本期即抽，uv workspace） |
| 4 | 契约 | proto 补全 + **Python 统一从 proto 生成**（betterproto 系，spike 定版本）；web 包纯增量 |
| 5 | 命名空间 | PG schema `rag` / Milvus `rag_knowledge_chunks` / Pulsar topic `rag-runs` / Redis 前缀 `rag:` |
| 6 | 路由 | 保持 `/api`（nginx `/agent/` 反代目标换容器，前端零改动） |
| 7 | 数据 | 无存量数据：Alembic 全新迁移历史（`rag` schema 全新建表） |
| 8 | 本地 LLM | 本机无 Ollama → 内置**协议级 LLM stub**（OpenAI 兼容；确定性 embedding；供本地 E2E） |
| 9 | 工具链 | Python 3.12 + uv；FastAPI + pydantic v2 + SQLAlchemy 2.0 async + Alembic + pymilvus + openai-python + PyJWT + redis-py + sse-starlette + PyMuPDF + python-docx + bcrypt + pulsar-client；ruff + mypy(strict) + pytest |
| 10 | 验收 | 独立扩缩容 4 条（03 §6.2）+ 全链路 E2E（上传→摄取→对话→任务）本地跑通 |

---

## 0.5 执行进度（本期范围已完成，本文档随之更新）

| 阶段 | 状态 | 证据 / 说明 |
|---|---|---|
| M0 契约与工程基座 | ✅ | proto 补全（纯增量,breaking 通过）；三端生成物（TS×2 + Python betterproto2 0.10.0，工具选型见 05 文档）；uv workspace + `agent-core`（12 模块）+ `apps/_template` |
| M1 数据与鉴权 | ✅ | `rag` schema 8 表 + `alembic_version`（Alembic 初始迁移）；JWT 双模 + 联邦身份；`/api/health` 三依赖全绿 |
| M2 运行引擎与队列 | ✅ | run-engine（先落库后广播/终态先事件后状态/断线补发）；Pulsar Shared 竞争消费 + ack/nack + 优雅退出 |
| M3 文档摄取 | ✅ | 中文文件名上传 → PyMuPDF/docx 解析 → 递归切分 → embedding 批处理 → PG+Milvus 双写；删文档清双端 |
| M4 对话与检索 | ✅ | 唯一检索出口（user 过滤写死）+ 流式 SSE（token/done/error）+ citations + 标题回填 |
| M5 Agent 任务 | ✅ | 4 工具 + 8 步循环；`tool_called → tool_result → final_answer` 事件链；会话详情回放 |
| M6 部署与 CI | ✅ | Python Dockerfile（容器冒烟通过：迁移 + 健康检查 + Pulsar 生产者）；prod compose（自建 Pulsar + 两角色）；Makefile；deploy.yml / proto.yml 切 Python |
| M7 验证与收尾 | ✅ | **E2E 26/26**（`tools/e2e_test.py`）；**扩缩容四条全过**（跨副本 SSE / 竞争消费 / 两层独立 / 滚动重启不丢）；**pytest 28 全绿**；README / CLAUDE.md / 05 契约文档 / debug 踩坑记录 |

**遗留（明确非本期）**：第二个业务服务（coding）的业务实现；K8s/KEDA（设计已给，单机 compose 先行）；
`buf validate`（值级约束升级，现为业务层显式校验）。

---

## 1. Wire 格式硬约束（来自 web 端源码逐行核对，必须对齐）

| 项 | 约束（以 Node 实际行为为准） |
|---|---|
| JSON 字段 | **camelCase**（`runId`/`documentId`/`createdAt`/`progressMsg`…） |
| 错误体 | `{code, message}`；删除类 204 无 body；提交类 202 |
| Chat SSE | `event: token\|done\|error`；`data` 自带 `type`：`{type:'token',value}` / `{type:'done',messageId,citations}` / `{type:'error',message}` |
| Run SSE | `id: <sequenceNo>`、`event: <eventType>`、`data: 整条 run_event 行` `{id,runId,sequenceNo,eventType,payload,createdAt}`（业务字段在 `payload` 下） |
| Run 事件名 | `run_started` / `run_completed` / `run_failed` / `step` / `tool_called` / `tool_result` / `final_answer`（web 监听列表含 `progress`/`ingestion_*`，但服务端实际发 `step`——**保持 Node 实际行为**） |
| 快照 | `GET /runs/:runId` → `{run, events}`；`GET /agent/sessions/:id` 的 runs 带 `events`（按 sequenceNo 升序） |
| run 字段 | `run.task`（用户气泡）、`status` 实际值 `queued/running/completed/failed` |
| 文档状态 | Node 实际写 `queued`（上传）→ `processing`（摄取中）→ `ready/failed`（对齐此行为） |
| citations | `[{chunkId, documentId, score}]`（Node 实际形状） |
| 上传 | multipart 字段名 `file`；中文文件名必须正确落库（Node 有 latin1→utf8 修复，Python 侧需验证） |
| 鉴权 | `Authorization: Bearer`；SSE 兜底 `?access_token=`；401 前端清 token 引导重登 |

---

## 2. 阶段划分与验收（M0–M7）

### M0 · 契约与工程基座
- **内容**：proto 补全（Req/Resp/事件/快照，纯增量）→ buf 增 Python 生成目标（betterproto 系，spike 定夺并钉版本）
  → TS 生成物刷新（node gen + `@talqora/agent-contracts`）→ uv workspace（根 pyproject + agent-core + rag-server）
  → `agent-core` 骨架（settings / logging / db / auth / queue / events / llm / vector / health）→ 服务模板 `apps/_template`
- **验收**：`buf lint` + `breaking` + freshness 通过；生成类型在 FastAPI 跑通（spike 报告）；`uv sync` 通过；
  ruff + mypy 通过。

### M1 · 数据与鉴权
- **内容**：SQLAlchemy 2.0 async 模型（`rag` schema，8 表）→ Alembic 初始迁移（含 `CREATE SCHEMA`）
  → JWT 双模鉴权（RS256 JWKS + HS256 兜底，alg 分发、iss/aud 校验、clockTolerance）→ 联邦身份（(iss,sub) 零接触）
  → `/api/health`（并行探活）+ `/api/auth/*`（register/login/me）
- **验收**：pytest 单测 + 集成（真 PG）；curl 走通 register → login → me。

### M2 · 运行引擎与队列
- **内容**：RunEngine（seq 分配 / emit 先落库后广播 / start / complete / fail / snapshot / getEventsSince）
  → Pulsar 封装（producer + Shared 订阅 consumer、ack/nack、优雅退出）→ worker 入口 + demo job
- **验收**：集成测试（真 PG+Redis+Pulsar）：入队→消费→事件序列正确；断线补发；Redis 广播跨副本可达。

### M3 · 文档摄取
- **内容**：上传（类型/大小/中文名）→ 解析（PyMuPDF/docx/md/txt）→ 切分（平移自研递归切分器 800/100）
  → embedding 批处理（16/批）→ PG+Milvus 双写（开写前幂等清场）→ documents CRUD（删文档清 Milvus+磁盘）
- **验收**：集成测试；本地真 Milvus 跑通一份中文 PDF 摄取（chunkCount/向量可检索）。

### M4 · 对话与检索
- **内容**：RagRetriever（`user_id` 过滤唯一出口）→ chat SSE（token/done/error，POST 手写 SSE）
  → conversations CRUD → 历史（最近 10 条）拼 prompt → citations 落库
- **验收**：SSE 端到端（stub LLM）逐 token 收帧；done 帧 citations 正确；会话标题回填。

### M5 · Agent 任务
- **内容**：ToolRegistry（retrieve_knowledge / list_documents / summarize_document / organize）
  → AgentRunner（8 步上限、工具异常回喂模型、final_answer 收敛）→ task-sessions CRUD → `/api/agent/tasks`
- **验收**：SSE 收到 `tool_called → tool_result → final_answer` 序列；任务会话 runs/events 可回放。

### M6 · 部署与 CI
- **内容**：Dockerfile（python:3.12-slim + uv，构建上下文含 agent-core）→ compose（新增 `pulsar`；
  `rag-http`/`rag-worker` 两角色、可 `--scale`、无固定 container_name、独立资源限制）
  → Makefile 切 Python → `deploy.yml` 切 Python（scp 上下文更新）→ `proto.yml` freshness 增加 Python 生成物路径
- **验收**：镜像构建成功；compose 全套起得来；CI 配置静态自查通过。

### M7 · 扩缩容验证与全链路 E2E
- **内容**：colima 起全套中间件（PG/Redis/Pulsar/Milvus）→ 应用（宿主 uv 运行，双副本）
  → 全链路 E2E 脚本（注册/登录 → 上传 → 摄取进度 → 对话流式 → 任务 + SSE）
  → 扩缩容 4 条验证 → README / CLAUDE.md 收尾
- **验收**：03 §6.2 四条（跨副本 SSE / 竞争消费不重复 / 两层互不影响 / 滚动重启不丢）+ E2E 全绿。

---

## 3. 测试策略

| 层 | 工具/方式 | 覆盖 |
|---|---|---|
| 单测 | pytest（纯逻辑，无外部依赖） | 切分器、解析器、run-engine 序号、casing 序列化、鉴权声明解析 |
| 集成 | pytest + 本地 colima 中间件（PG/Redis/Pulsar/Milvus） | 事件溯源、队列消费、摄取双写、联邦身份 |
| E2E | 真实全栈 + 脚本断言（LLM 用 stub） | 全流程 + SSE 帧格式 + 扩缩容 4 条 |
| 契约 | buf freshness + wire 格式断言 | 生成物不漂移；camelCase/事件名/字段形状 |

## 4. 风险与对策

| 风险 | 对策 |
|---|---|
| betterproto pydantic 与 pydantic v2/FastAPI 兼容性未知 | **M0 先 spike**；不可用则回退"生成 dataclass + 边界序列化助手"，仍保持 proto 单一来源 |
| pulsar-client 无 asyncio / wheel 缺失 | 验证后定：同步调用走 `to_thread` 包装，或 worker 内线程化消费 |
| colima 仅 2GiB 内存（Milvus+Pulsar 偏重） | 先检查宿主内存，必要时 `colima stop && colima start --memory 8`（当前无其他容器运行） |
| PyMuPDF/bcrypt 等 C 扩展安装 | uv 优先 manylinux/macos wheel；国内源加速 |
| 长任务优雅退出与重投叠加 | 幂等设计保留（摄取清场/事件溯源）；`stop_grace_period` 显式配置 |

## 5. 切换 checklist（M6/M7 收口）

- [ ] `deploy.yml` 切 Python（构建上下文 = `apps/rag-server` + `packages/agent-core` + `docker/`）
- [ ] prod compose：移除 node 服务，加 `rag-http` / `rag-worker` / `pulsar`
- [ ] nginx `/agent/` 反代目标换 `rag-http`（路径/协议不变）
- [ ] 本地 E2E 全绿后合并 master（node 目录保留对照）
