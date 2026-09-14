# Agent Server

ChatGPT 式个人知识助手后端(单仓多服务):用户上传资料 → 自动解析/切分/向量化/组织 → 基于自己的资料多轮对话 + agent 任务。

## 形态(Python 重写后)

- **`apps/rag-server/`** — RAG 知识库服务(Python):同代码库双角色
  **rag-http**(uvicorn,HTTP + SSE)+ **rag-worker**(Pulsar 消费者);技术栈 FastAPI + SQLAlchemy(async)+
  Alembic + Pulsar + Milvus + Redis + OpenAI 兼容 LLM;契约从 proto 生成(betterproto2,禁止手改)。
- **`packages/agent-core/`** — 多服务共享库:auth(JWKS 双模验签 + 联邦身份)/ run-engine(事件溯源 + SSE 补发)/
  queue(Pulsar 封装)/ llm / vector / 配置与日志。新服务从这里继承,不复制。
- **`apps/node-server/`** — Node 版(重写前)对照参考,不再部署。
- **`apps/_template/`** — 新服务脚手架(复制 + 改命名空间,见其 README)。

架构与决策文档在 **`docs/架构设计/`**:01 多服务评估 → 02 队列/实时评审 → 03 多服务架构与独立扩缩容 →
04 重写路线图 → 05 契约生成与 FastAPI 整合。

## 本地启动

```bash
make dev          # 一键:建 env + uv sync + 起中间件 + 迁移 + 并发跑 rag-http(:3101)/rag-worker
make llm-stub     # (另开终端)本机无 Ollama / 真实 API key 时,起协议级 LLM stub(端口同 Ollama)
make e2e          # 全链路端到端(注册 → 上传 → 摄取 SSE → 对话 SSE → agent 工具链)
```

其它:`make middleware`(只起中间件) · `make down`(停) · `make migrate` · `make test` · `make lint` ·
`make scaling`(独立扩缩容验证,需两个 rag-http 副本)。

编排在 `docker/`:
- `docker-compose.dev.yml` — 本地开发,只起中间件(postgres/redis/pulsar/etcd/minio/milvus),业务跑宿主机;
- `docker-compose.prod.yml` — 全栈(rag-http/rag-worker + 自建 Pulsar;Milvus 对象存储用腾讯 COS)。

## 关键约定(详见 docs/架构设计/)

- **契约**:proto(`proto/ourchat/agent/v1/`)是业务类型的单一来源;TS/Python 各自生成;JSON 线格式 camelCase。
- **命名空间**:PG schema `rag` · Pulsar topic `rag-runs` · Redis 前缀 `rag:` · Milvus collection `rag_knowledge_chunks`。
- **多租户**:一切检索/读写按 user 过滤(检索过滤写死在唯一出口 `RagRetriever`/`search_by_user`)。
- **可靠投递**:Pulsar 至少一次 + 业务幂等(摄取开写前清场);进度 = PG 事件溯源 + Redis pub/sub 扇出 + SSE 断线补发。
