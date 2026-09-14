# rag-server 镜像:python:3.12-slim + uv(与开发环境同款依赖解析)。
#
# 构建上下文 = **仓库根**(需要 pyproject.toml / uv.lock / packages/agent-core / apps/rag-server):
#   docker build -f apps/rag-server/Dockerfile -t rag-server:local .
# 角色由入口决定(同镜像双角色,对齐"双进程单镜像"):
#   HTTP   → 默认 CMD(先 alembic upgrade head 再起 rag-http)
#   worker → compose 覆盖 command 为 rag-worker(不迁移)
#
# 注意:两阶段的 venv 路径必须一致(/app/.venv)——venv 内 console script 的 shebang 写死绝对路径,
# 路径不一致会导致 "alembic: not found"(踩过)。

# ========== 阶段一:依赖构建(uv workspace,非可编辑安装 → 运行期与源码路径无关) ==========
FROM python:3.12-slim AS builder

# uv 从 PyPI 安装(避免依赖 ghcr.io;版本与本地开发钉一致)。构建期不下载 Python,用镜像自带 3.12。
ARG UV_VERSION=0.12.0
RUN pip install --no-cache-dir "uv==${UV_VERSION}"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# 与运行阶段同路径(venv shebang 兼容)
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/agent-core ./packages/agent-core
COPY apps/rag-server ./apps/rag-server

# --frozen:锁文件即真相;--no-dev:不带测试/类型检查工具;--no-editable:装成 wheel
RUN uv sync --frozen --no-dev --all-packages --no-editable

# ========== 阶段二:运行 ==========
FROM python:3.12-slim

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# curl:容器健康检查
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
# alembic.ini + alembic/ 在运行期要用于迁移
COPY --from=builder /app/apps/rag-server /app/apps/rag-server

WORKDIR /app/apps/rag-server
EXPOSE 3101

# HTTP 角色:先应用迁移(幂等)再起服务;worker 由 compose 覆盖 command(见 docker-compose.prod.yml)
CMD ["sh", "-c", "alembic upgrade head && rag-http"]
