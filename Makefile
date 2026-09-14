# agent-server 本地开发编排(Python 版:rag-server + agent-core)
#
# 一键启动:  make dev
#   首次自动:建 env(apps/rag-server/.env)+ uv sync + 起中间件 + 迁移,
#   随后并发跑 rag-http(:3101)/ rag-worker,合并输出,Ctrl-C 一起停。
# 本地 LLM:若本机没有 Ollama / 真实 API key,另开终端 `make llm-stub`(协议级模拟,端口同 Ollama)。
# 其它:      make middleware / down / env / deps / migrate / llm-stub
#            make test / lint / e2e / scaling(需双副本) / proto
#
# 中间件(postgres/redis/pulsar/etcd/minio/milvus)跑 docker;业务跑宿主机热重载。
# 端口偏移见 docker/docker-compose.dev.yml(5433/6380/6650/19530,避开 our-chat)。

DEV_COMPOSE := docker/docker-compose.dev.yml
APP_DIR     := apps/rag-server

.PHONY: dev middleware down env deps migrate llm-stub test lint e2e scaling proto proto-sync

# 一键起全部:env/依赖就绪 → 起中间件 → 等 PG → 迁移 → 并发跑 http + worker(Ctrl-C 一起退出)
dev: env deps middleware
	@printf '⏳ 等待 PostgreSQL'; \
	until docker exec agent-postgres pg_isready -U agent >/dev/null 2>&1; do printf '.'; sleep 1; done; echo ' ✓'
	@echo '⏩ 应用数据库迁移'; cd $(APP_DIR) && uv run alembic upgrade head
	@echo '▶ rag-http(HTTP):3101 · rag-worker(Ctrl-C 全部停止)'
	@trap 'kill 0' INT TERM EXIT; \
	( cd $(APP_DIR) && uv run rag-http ) & \
	( cd $(APP_DIR) && uv run rag-worker ) & \
	wait

# 只起中间件(postgres + redis + pulsar + etcd + minio + milvus)
middleware:
	docker compose -f $(DEV_COMPOSE) up -d

# 停中间件
down:
	docker compose -f $(DEV_COMPOSE) down

# 生成本地 env(幂等;不存在才建)
env:
	@test -f $(APP_DIR)/.env || { cp $(APP_DIR)/.env.example $(APP_DIR)/.env; echo "✓ 已生成 $(APP_DIR)/.env(按需改 LLM_* / JWT_SECRET)"; }

# 安装/同步依赖(uv workspace:rag-server + agent-core)
deps:
	uv sync --all-packages

# 应用数据库迁移(改模型后:先 alembic revision --autogenerate 再 upgrade)
migrate:
	cd $(APP_DIR) && uv run alembic upgrade head

# 本地 LLM 协议级 stub(OpenAI 兼容;无 Ollama/API key 时用于端到端联调)
llm-stub:
	uv run python tools/llm_stub.py

# 测试(单测/集成;全链路端到端见 e2e)
test:
	uv run pytest

# 质量门禁:lint + 格式 + 严格类型
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy apps/rag-server/src packages/agent-core/src

# 全链路端到端(需中间件 + llm-stub + rag-http + rag-worker 已启动)
e2e:
	uv run python tools/e2e_test.py

# 独立扩缩容验证(需两个 rag-http 副本 :3101/:3102 + 至少一个 rag-worker)
scaling:
	uv run python tools/scaling_test.py

# 从 proto 生成契约类型(TS 两份 + Python betterproto2;本地插件需 uv tool install betterproto2_compiler==0.10.0)
proto:
	buf generate

# 从 our-chat(canonical)同步 agent 域契约副本后重新生成。需 our-chat 与本仓库同级
proto-sync:
	rsync -a --delete ../our-chat/proto/ourchat/agent/ proto/ourchat/agent/
	buf generate
