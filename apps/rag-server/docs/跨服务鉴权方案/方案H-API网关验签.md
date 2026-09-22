# 方案 H:API Gateway / Edge 验签

> 返回 [索引](./跨服务鉴权方案分析.md)
> 横向跳转:[A](./方案A-独立账号.md) · [B](./方案B-对称密钥前端持JWT.md) · [C](./方案C-对称密钥Cookie兜底.md) · [D](./方案D-非对称密钥JWKS.md) · [E](./方案E-TokenExchange.md) · [F](./方案F-OAuth2授权码PKCE.md) · [G](./方案G-BFF会话.md) · **H**

---

## 1. 原理

把 JWT 验证从 agent-server **下沉到 gateway 层**(Nginx + lua / Kong / APISIX / Envoy):

```
                  ┌──────────────────────────────┐
Browser ──Bearer──│  API Gateway(验签 + 注入)  │──→ agent-server
                  │  - 验 JWT 签名               │   (信任 gateway)
                  │  - 注入 X-User-Id 头         │
                  └──────────────────────────────┘
```

agent-server 不再验 JWT,只读 gateway 注入的 `X-User-Id` 等头。

## 2. 优劣

| 优 | 劣 |
|---|---|
| 后端服务全部省掉验签代码 | gateway 故障 = 全站登录失败 |
| 验签实现集中,易于统一升级 | 后端"裸"接受头 → 内网必须严格隔离 |
| 限流 / WAF 可以同层做 | 本地开发要起 gateway,联调成本 |
| 集中审计 | 不适合 agent-server 这种"想保留自主鉴权"的场景 |

## 3. 业界

字节、阿里、腾讯内部大量服务走这套模式(网关团队负责鉴权,业务团队不操心)。但本项目还在 MVP 阶段,引入 gateway 杀鸡用牛刀。

---

## 横向关联

- **跟 [方案 G](./方案G-BFF会话.md) 的关系**:G 是"前端定制代理",H 是"统一鉴权代理",层级不同但都属于"代理鉴权"
- **跟其他方案的关系**:H 是独立的部署层方案,可与 B/D/F 任意组合(gateway 验 token 后,后端可仍按 Bearer/JWKS 等方式接入)
- **场景判别**:有专门的网关 / 平台团队 → H 是企业级最佳;团队自己做小项目 → 自带验签即可,gateway 是负担
