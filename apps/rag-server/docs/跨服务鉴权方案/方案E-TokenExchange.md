# 方案 E:Token Exchange(RFC 8693)

> 返回 [索引](./跨服务鉴权方案分析.md)
> 横向跳转:[A](./方案A-独立账号.md) · [B](./方案B-对称密钥前端持JWT.md) · [C](./方案C-对称密钥Cookie兜底.md) · [D](./方案D-非对称密钥JWKS.md) · **E** · [F](./方案F-OAuth2授权码PKCE.md) · [G](./方案G-BFF会话.md) · [H](./方案H-API网关验签.md)

---

## 1. 原理

前端持有 our-chat 的 token,经标准化端点把它"兑换"成 agent-server 的 token:

```
POST /oauth2/token HTTP/1.1
Host: agent-server.com
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:token-exchange
&subject_token=<our-chat token>
&subject_token_type=urn:ietf:params:oauth:token-type:jwt
&audience=agent-server
```

agent-server 验证 subject_token(用 our-chat 的公钥 / 共享 secret),签发自己的 token 返回。

## 2. 跟 B/D 的区别

- **B/D**:our-chat 签的 token 直接被 agent-server 接受
- **E**:agent-server 接受 our-chat 的 token 但**不直接信任用作鉴权**,而是 mint 一个 agent-server 自己签发的 token,客户端用新 token 后续请求

## 3. 价值

- agent-server 的 token 可以包含 agent-server 特有的字段(权限范围、租户 ID、内部 user 编号映射)
- 撤销时:agent-server 可以独立撤销自己签发的 token,不受 our-chat token 状态影响
- 跨组织集成的标准化 token 流(SaaS / B2B 集成必备)

## 4. 代价

- 多一次往返(每次 our-chat token 过期都要重新 exchange)
- 实现复杂度上升,需要严格的 OAuth2 库支持
- 对 MVP 而言完全过度设计

## 5. 适用场景

- 跨组织 SaaS 集成(Slack 集成第三方应用就是这套)
- 多个 resource server 各自有独立权限语义
- 已经在跑 OAuth2 / OIDC 生态

---

## 横向关联

- **跟 [方案 D](./方案D-非对称密钥JWKS.md) 的关系**:D 让 agent-server **直接信任** our-chat 签的 token;E 让 agent-server **接受但不直接信任**,二次签发自己的 token。语义控制粒度 E 更细
- **跟 [方案 F](./方案F-OAuth2授权码PKCE.md) 的关系**:E 是 F 生态里的一种 grant type,通常在 OAuth2 框架内使用
- **场景判别**:权限语义两边一致 → D 够用;权限语义两边不同(如 our-chat 是用户身份,agent-server 是带 scope 的 API 访问) → E 才有价值
