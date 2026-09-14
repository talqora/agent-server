# 服务模板(_template)

新建 agent 服务的脚手架:复制本目录为 `apps/<service>-server/`,按下面清单替换命名空间即可。

## 使用步骤(对齐 docs/架构设计/03 §7"服务接入 checklist")

1. **复制**:`cp -r apps/_template apps/<service>-server`,然后全局替换占位符:
   - `<service>` → 服务名(如 `coding`);`<SERVICE>` → 大写形式(如 `CODING`);
   - `_template` → `<service>-server`(pyproject 名称与构建配置)。
2. **注册到工作区**:根 `pyproject.toml` 的 `[tool.uv.workspace].members` 增加
   `"apps/<service>-server"`,执行 `uv sync --all-packages`。
3. **命名空间**(共享基础设施划地盘,禁止与既有服务串台):
   - PG:schema `<service>`(迁移 env.py 的 `SCHEMA` 常量);
   - Pulsar:topic `<service>-runs`;Redis 频道前缀 `<service>:`(由 `service_name` 决定);
   - Milvus:collection `<service>_*`(如需要);
   - HTTP 路由:nginx 加 `location /agent/<service>/`(当前 rag 占 `/agent/`)。
4. **契约**:新 proto 域 `ourchat/<service>/v1/`,在 `buf.gen.yaml` 增加该域的输出目标;
   生成物进 `src/<service>_server/contracts/gen/`(禁止手改)。
5. **依赖**:只依赖 `agent-core`(共享基座)+ 自己的领域依赖;跨服务协作走 API/事件,禁止跨服务读表。
6. **部署**:`docker/docker-compose.prod.yml` 加两个角色(同镜像不同入口);CI `deploy.yml`
   的 scp 源与 `proto.yml` 的 freshness 路径各加一条。
7. **验证**:跑 docs/架构设计/03 §6.2 的独立扩缩容四条(跨副本 SSE / 竞争消费 / 两层独立 / 滚动重启不丢)。

## 目录约定

```
apps/<service>-server/
├── pyproject.toml            # 依赖 + rag-http/rag-worker 式双入口脚本
├── alembic.ini / alembic/    # 迁移(env.py 里 SCHEMA 换成 <service>)
├── src/<service>_server/
│   ├── main.py               # HTTP 角色入口(uvicorn)
│   ├── worker.py             # worker 角色入口(队列消费者)
│   ├── settings.py           # 继承 agent-core BaseServiceSettings,追加领域配置
│   ├── context.py            # build_core/close_core(装配 agent-core 组件)
│   ├── deps.py / errors.py   # FastAPI 依赖与统一错误处理
│   ├── contracts/            # proto 生成物 + camelCase 适配(apply_camel_aliases)
│   ├── db/                   # ORM 模型 + agent-core 端口适配器
│   └── modules/<domain>/     # 领域模块(router/service/...)
└── tests/
```
