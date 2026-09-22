# 方案 A:独立账号 ── 零改动 baseline

> 返回 [索引](./跨服务鉴权方案分析.md)
> 横向跳转:**A** · [B](./方案B-对称密钥前端持JWT.md) · [C](./方案C-对称密钥Cookie兜底.md) · [D](./方案D-非对称密钥JWKS.md) · [E](./方案E-TokenExchange.md) · [F](./方案F-OAuth2授权码PKCE.md) · [G](./方案G-BFF会话.md) · [H](./方案H-API网关验签.md)

---

## 1. 原理

两个后端各自管理用户、各签自己的 token,前端维护两套 session。

```
┌─────────────────────────┐
│        前端 SPA         │
├─────────────────────────┤
│ ourChatHttp(cookie)    │  ←──→  our-chat /api/...
│ agentHttp(localStorage)│  ←──→  agent-server /...
└─────────────────────────┘
```

## 2. 实现路径

1. 前端新建 `agentHttp` axios 实例,baseURL 指 agent-server
2. 拦截器从 localStorage / Redux 读 agent-server 的 JWT,塞 `Authorization`
3. 第一次访问 AgentChatPanel 时弹一个登录表单(`username/password` → `POST /auth/login`)
4. agent-server 完全不动

## 3. 优劣

| 优 | 劣 |
|---|---|
| 零后端改动 | **用户登两次** —— 体验明显割裂 |
| agent-server 契约不被任何客户端污染 | 用户名/密码可能不同,前端要维护两套表单 |
| Flutter 端可直接复用 | 简历上无 "single sign-on" 卖点 |
| 半天可演示 | 第二阶段必然要重做鉴权,投入会扔掉一部分 |

## 4. 适用场景

- 项目早期验证 API 链路
- 两个后端归属不同组织(SaaS 集成第三方)
- 用户群体本来就预期"这是两个产品"(类似登录 GitHub 后再绑定 Vercel)

## 5. 不适用场景

- 同一产品矩阵内的多服务(用户视角应该是"一个产品")
- 任何要在校招简历上写"集成两个独立后端"的演示项目 —— 面试官会反问"凭什么用户要登两次?"

---

## 横向关联

- **跟 [方案 B](./方案B-对称密钥前端持JWT.md) 的关系**:B 是 A 的"SSO 化"——同样维护两套 token,但用户只登一次,by 后端串起来
- **跟 [方案 F](./方案F-OAuth2授权码PKCE.md) 的关系**:F 是 A 的"标准化"——把"用户登 IdP 一次,各 resource server 拿同一 token"做成行业协议
- **看 [推荐路径 §6](./跨服务鉴权方案分析.md#6-推荐路径对本项目)** 了解何时该选 A
