# agent-server 对外入口方案对比：nginx 同源反代 vs 独立子域名

> 决策文档。背景：单台 7.4 GiB 服务器上，our-chat（IM 全栈）与 agent-server（AI 后端）同机部署，要决定**浏览器如何访问 agent-server**。
> 结论先放这里：**单机场景选「方案 A 同源反代」**；理由见 §5。

---

## 0. 背景与关键事实

- **一台机**：our-chat（postgres/redis/server/gateway/nginx）+ agent-server（postgres/redis/milvus 栈/node-server/worker）同机。
- **唯一公网入口**：our-chat 的 nginx（:80/:8080），已反代 server(3007)/gateway(8090)。agent 的 node-server 跑在 **:3101**（HTTP + SSE 流式）。
- **前端是 our-chat 的 web**，通过构建期变量 `VITE_AGENT_API_BASE` 决定 agent 的基址（见 `web/src/views/agentView/api.ts`）。
- **鉴权模型（决定性事实）**：agent 用 **`Authorization: Bearer <RS256 JWT>`**，token 由 our-chat 作为 IdP 签发、agent 用 JWKS 公钥验签（`apps/node-server/src/modules/auth/jwt.strategy.ts`，全局 JWT 守卫）。SSE 因 `EventSource` 不能带自定义头，**兜底**支持 `?access_token=` query。
  - 推论：**agent 不依赖 cookie**。所以"必须同源才能带 HttpOnly cookie"这条（对 our-chat 自身成立）**对 agent 不成立**——Bearer 头天然跨域可用。跨域的代价只剩 **CORS**（agent 已用 `CORS_ORIGINS` 白名单管理，`main.ts`）。

> 这一节很重要：很多人默认"微服务要同源"，其实那是 cookie 鉴权的约束。agent 是 Bearer 鉴权，**同源不是功能必需，只是省事**。下面据此客观对比。

---

## 1. 两个方案怎么工作

### 方案 A：同源反代（在 our-chat 的 nginx 加 `/agent/`）
```
浏览器 https://chat.example.com/agent/api/...
        └─► our-chat nginx  (location /agent/)
              └─► agent node-server :3101  /api/...
```
- 前端：`VITE_AGENT_API_BASE = https://chat.example.com/agent/api`（可由 our-chat 的 `WEB_PUBLIC_ORIGIN` 直接派生，不必单独配）。
- 同源 → **无 CORS**；复用 our-chat 的**同一个域名 + 同一张 TLS 证书**；**不需要新 DNS**。
- agent 仍然独立仓库 / 独立镜像 / 独立 compose / 独立 CI/CD，只是"对外那一跳"借道 our-chat 的 nginx。

### 方案 B：独立子域名（`agent.example.com`）
```
浏览器 https://agent.example.com/api/...
        └─► agent 自己的 ingress (独立 nginx/caddy + TLS)
              └─► agent node-server :3101
```
- 前端：`VITE_AGENT_API_BASE = https://agent.example.com/api`。
- 跨域 → **必须 CORS**（`CORS_ORIGINS=https://chat.example.com` + 预检 OPTIONS）；需要**新 DNS 记录** + **独立 TLS 证书**（或泛域名）；要给 agent 配**自己的 80/443 入口**。

---

## 2. 逐维度对比

| 维度 | A 同源反代 | B 独立子域名 |
|---|---|---|
| **CORS** | 不需要（同源） | 必须：白名单 + 预检；`credentials:true` 时不能用 `*`，要精确回显 origin |
| **DNS** | 不加记录 | 需加 `agent.example.com` A 记录 |
| **TLS 证书** | 复用 our-chat 现有证书 | 需为子域名再签一张（或上泛域名证书） |
| **鉴权(Bearer)** | 正常 | 正常（Bearer 不受同源限制） |
| **Cookie** | agent 不用 cookie，无影响 | 无影响 |
| **SSE 流式** | nginx 关 buffering + 长超时（一处配） | agent 自己的 ingress 同样要配（另一处） |
| **对外暴露面** | agent 只在内网，nginx 仅放行 `/agent/` | agent 需要自己的公网 443 入口（多一个对外面） |
| **部署耦合** | 改 agent 对外路径要动 our-chat nginx（但路径稳定，近乎一次性） | 完全解耦，agent 自管入口 |
| **故障域** | our-chat nginx 是两者共同入口（它挂两个都挂） | 入口隔离，互不影响 |
| **运维复杂度(单机)** | 低：一个域名 / 一张证书 / 一处 nginx | 高：多一条 DNS + 一张证书 + 一套 ingress |
| **前端配置** | 由 `WEB_PUBLIC_ORIGIN` 派生，零额外变量 | 需单独维护一个 agent 域名变量 |
| **未来拆机/独立扩缩** | 要回退成 B（成本低，仅换基址+配入口） | 天生适合 |

---

## 3. 关键技术细节

### 3.1 方案 A 的 nginx 配置（加到 our-chat 的 `docker/nginx/conf.d/default.conf`）
```nginx
# agent-server 同源反代：剥掉 /agent/ 前缀后转发到 agent :3101
location /agent/ {
    # 末尾的 / 会把 /agent/api/x 重写为 /api/x，正好匹配 agent 的 /api 前缀
    proxy_pass http://agent-node-server:3101/;      # 见 3.3 内网互通
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    # SSE：必须关缓冲并拉长超时，否则流式 token 会被整段缓冲 / 超时掐断
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
}
```
> `proxy_pass` 尾斜杠是坑点：**带 `/` 剥前缀**、**不带 `/` 保留前缀**，配反了会 404。本服务路由在 `/api` 下（healthcheck 即 `/api`），所以要剥前缀。

### 3.2 两方案共同的「JWKS 可达性」（与入口选择无关）
agent 要拿 our-chat 的公钥验签 → 访问 our-chat 的 `/.well-known/jwks.json`。当前 our-chat 的 nginx **没有**代理 `/.well-known/`（会落到 SPA 首页），所以**两方案都要**给 our-chat 的 nginx 补一条：
```nginx
location /.well-known/ {           # JWKS 本就该公开
    proxy_pass http://server:3007;
    proxy_set_header Host $host;
}
```
然后 agent 配 `OAUTH_JWKS_URI` 指向 our-chat（见 3.3）。

### 3.3 服务间内网互通（正交于入口选择）
nginx→agent、agent→our-chat(JWKS)、server→agent 这几条**内网调用**怎么连，有两种接法：

- **接法①：共享 docker 外部网络（推荐，最干净）**
  服务器上建一次 `docker network create oc-shared`；our-chat 的 nginx/server、agent 的 node-server 都接入它。然后**按容器名直连**：nginx → `http://agent-node-server:3101`，agent → `http://server:3007/.well-known/jwks.json`。无需暴露宿主机端口。
- **接法②：host.docker.internal + 本机端口**
  agent compose 发布 `127.0.0.1:3101:3101`（只绑本机、不公网）；nginx/server 经 `host.docker.internal:3101` 访问 agent；agent 经 `host.docker.internal:8080/.well-known/jwks.json` 访问 our-chat（需容器加 `extra_hosts: ["host.docker.internal:host-gateway"]`）。两套 compose **不共享网络**，更解耦，但要管端口。

> agent 现有默认值用的是接法②（`OAUTH_ISSUER/OAUTH_JWKS_URI=http://host.docker.internal:3007`）。**注意**：our-chat 没把 3007 暴露到宿主机，所以接法②要么改 our-chat 暴露 3007，要么把 JWKS 走 nginx（`host.docker.internal:8080/.well-known/jwks.json`）。综合看 **接法① 共享网络更省心**。

### 3.4 方案 B 的额外落地项
- DNS：`agent.example.com → 服务器 IP`。
- TLS：子域名证书（Let's Encrypt 单域名或泛域名）。
- agent 入口：另起 nginx/caddy 反代 :3101 并终止 TLS，或让 agent 直接挂 443。
- CORS：`CORS_ORIGINS=https://chat.example.com`；SSE 的 `?access_token` 跨域也要在白名单内。

---

## 4. 踩坑清单
1. **SSE 不关 nginx buffering** → 前端收不到增量、或长连接被默认 60s 读超时掐断。A/B 都要处理（A 在 our-chat nginx、B 在 agent 自己的 ingress）。
2. **方案 A 的 `proxy_pass` 尾斜杠**：剥/不剥前缀，配错直接 404。
3. **方案 B 的 CORS + `credentials:true`**：不能 `*`，必须精确回显 origin；漏配预检（OPTIONS）会让带 `Authorization` 头的请求全挂。
4. **JWKS 不可达**（两方案通病）：忘了给 our-chat nginx 开 `/.well-known/`，agent 启动验签就拉不到公钥。
5. **方案 B 多一个失效点**：子域名证书过期 / DNS 没生效 → agent 整个不可达；方案 A 借 our-chat 证书，少一个独立失效源。
6. **token 进 access log**（两方案）：SSE 的 `?access_token=` 是兜底手段，会落 nginx/agent 的 access log，注意日志脱敏或缩短 token TTL。

---

## 5. 推荐结论

**单机、个人项目、agent 用 Bearer（跨域无鉴权障碍）→ 选「方案 A 同源反代」。**

决断理由（排序）：
1. **省四样东西**：单机下 A 砍掉了 DNS、独立 TLS 证书、CORS、第二套 ingress；B 为了"架构独立"把这四样都加回来，单机收益对不上成本。
2. **agent 鉴权是 Bearer**，跨域本不影响功能——B 唯一相对 A 的"功能性"优势（独立）在单机上用不到。
3. **前端配置更省**：A 下 `VITE_AGENT_API_BASE` 由 `WEB_PUBLIC_ORIGIN` 直接派生，不必新增变量。
4. **耦合可控**：A 的"耦合"只是 our-chat nginx 里一条稳定的 `/agent/` location，agent 仍然独立仓库/独立部署/独立 CI/CD。

**何时切换到 B**：当 agent 要**拆到独立服务器**、**独立扩缩容/独立团队运维**、或**对第三方开放需独立域名品牌**时。迁移成本低——把 `VITE_AGENT_API_BASE` 换成子域名、给 agent 配独立 ingress + CORS 即可，业务代码不动。

---

## 6. 选 A 后的落地改动清单（供后续 CI/CD 配置）

**our-chat 仓库**
- `docker/nginx/conf.d/default.conf`：加 `location /agent/`（反代 agent:3101，SSE 配置）+ `location /.well-known/`（反代 server:3007）。
- 内网互通用 **接法①**：compose 让相关服务接入外部网络 `oc-shared`（部署机一次性 `docker network create oc-shared`）。
- web 构建：`VITE_AGENT_API_BASE = ${WEB_PUBLIC_ORIGIN}/agent/api`（加到 web 的构建参数；因 web 在 our-chat 仓库，这条是 our-chat 的 CI 配置）。

**agent-server 仓库**
- `docker/docker-compose.prod.yml`（pull-only）：node-server 接入 `oc-shared` 网络；**去掉 minio 服务**，milvus 的 `MINIO_*` 指向腾讯 COS；不对公网暴露 3101（仅内网/共享网络）。
- `.env`（由 CI 生成）：`OAUTH_JWKS_URI=http://server:3007/.well-known/jwks.json`（经共享网络按容器名）、`OAUTH_ISSUER=<WEB_PUBLIC_ORIGIN>`、`CORS_ORIGINS` 留空（同源）、`LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`（阿里千问，OpenAI 兼容）、`LLM_API_KEY=<secret>`、`MILVUS_*`、COS 凭据等。
- `.github/workflows/deploy.yml`：同 our-chat 模式（environment=pro、构建 node-server 镜像推 GHCR、SSH 部署到 `/opt/agent-server`）。

> 注意 **embedding 维度**：现配 `nomic-embed-text`=768 维。换成阿里千问 embedding（如 `text-embedding-v3`）维度不同（常见 1024），`MILVUS_VECTOR_SIZE` 必须同步改，且**已建的向量集合要重建**——否则维度不匹配写入失败。这点在切换 embedding 提供方时务必对齐。
