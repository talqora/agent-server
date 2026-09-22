# 方案 B:对称密钥 + 前端持 JWT

> 返回 [索引](./跨服务鉴权方案分析.md)
> 横向跳转:[A](./方案A-独立账号.md) · **B** · [C](./方案C-对称密钥Cookie兜底.md) · [D](./方案D-非对称密钥JWKS.md) · [E](./方案E-TokenExchange.md) · [F](./方案F-OAuth2授权码PKCE.md) · [G](./方案G-BFF会话.md) · [H](./方案H-API网关验签.md)

---

## 1. 原理

- our-chat 后端登录时,**额外签一个 non-HttpOnly cookie**(或写到响应 body),内含一个用 **与 agent-server 共享的 secret** 签的 JWT
- 前端 JS 能读到这个 token,塞到 `Authorization: Bearer` 头给 agent-server
- agent-server 完全不变,仍走它的 JwtAuthGuard

```
登录:
  Browser ──POST /api/login──→ our-chat server
          ←──Set-Cookie: agent_jwt=...(non-HttpOnly, 15min)──
          ←──Set-Cookie: ourchat_token=...(HttpOnly, 7day)──

调 agent-server:
  Browser JS reads document.cookie → 取出 agent_jwt
  Browser ──Authorization: Bearer agent_jwt──→ agent-server
                                              ↓
                                       verify with shared secret
```

## 2. 实现路径

**our-chat 后端**(改动量:登录/注册/refresh 三处,每处加 5 行):

```ts
// 用与 agent-server 共享的 JWT_SECRET 单独签一个短期 token
const agentToken = jwt.sign(
  { sub: user.id, username: user.username },
  process.env.AGENT_JWT_SECRET,
  { expiresIn: '15m', issuer: 'our-chat' },
);
res.cookie('agent_jwt', agentToken, {
  httpOnly: false,        // 关键:让前端 JS 能读到
  sameSite: 'lax',
  secure: process.env.NODE_ENV === 'production',
  maxAge: 15 * 60 * 1000,
});
```

**前端**(改动量:一个新 axios 实例):

```ts
const agentHttp = axios.create({ baseURL: AGENT_BASE });

const readCookie = (name: string) => {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
};

agentHttp.interceptors.request.use((config) => {
  const token = readCookie('agent_jwt');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

agentHttp.interceptors.response.use(undefined, async (err) => {
  if (err.response?.status === 401) {
    // 触发 our-chat 的 refresh,会同时刷新 agent_jwt cookie
    await ourChatHttp.post('/api/refresh');
    return agentHttp(err.config); // 重试
  }
  throw err;
});
```

**agent-server**:零改动。

## 3. 优劣

| 优 | 劣 |
|---|---|
| agent-server 契约纯净(仍是 Bearer) | non-HttpOnly cookie 有 **XSS 暴露风险** |
| 部署拓扑无约束(不同域也跑) | XSS 缓解依赖短 expiry + 强 CSP |
| Flutter 不受影响(走同样 Bearer) | 需要管理共享 secret(运维注意) |
| 401 → refresh 可挂在 our-chat 现有逻辑上 | 前端要写一份读 cookie 的逻辑 |
| 演进到 OAuth2 自然(B 就是 OAuth2 access token 的简化版) | |

## 4. 适用场景

- **MVP 阶段优选**:工作量最小,后端只动 our-chat 一处,演进路径明确
- 单一组织、两个独立后端、Web + Native 多端
- 不需要立即上 OAuth2 标准但有未来演进意愿

## 5. 踩坑

| 坑 | 缓解 |
|---|---|
| Cookie 跨域时 SameSite=None + Secure 是硬约束(Safari ITP / Chrome 第三方 cookie 政策) | 同域部署 / `SameSite=Lax` 即可,跨域时显式配置 |
| `document.cookie` 的字符串 parse 易错 | 用 `js-cookie` 库或写好的正则,不要手撸 |
| Token 过期前的 race(同一时刻多请求同时 401) | refresh 走互斥锁 + 等待队列(our-chat http.ts 已有) |
| 多浏览器标签页同时刷新 token | localStorage event 同步,或干脆每个 tab 各管各 |

## 6. 多端兼容性的诚实评估

B 方案在浏览器上是优解,**但严格说,它的"用户一次登录两边通"只在浏览器场景成立**:

- **Web**:登 our-chat → cookie 自动落地 → JS 读 cookie 塞头,完成 SSO
- **Flutter / Native**:**没有浏览器 cookie 容器**,凭什么登 our-chat 就能拿到 agent JWT?要么独立登 agent-server(退化到方案 A),要么必须前置一个 OAuth 流(等于上方案 F)

**所以本方案对多端等价是 Web-only 的优化。** 真正多端等价的鉴权必须用 OAuth 2.0 ([方案 F](./方案F-OAuth2授权码PKCE.md)),见 [索引文档 §7 重审](./跨服务鉴权方案分析.md#7-重审oauth-20-是不是最佳实践)。

---

## 横向关联

- **跟 [方案 A](./方案A-独立账号.md) 的关系**:B 是 A 的"由后端串起来"版,用户少登一次
- **跟 [方案 C](./方案C-对称密钥Cookie兜底.md) 的关系**:同样共享密钥,但 C 让 agent-server 直接读 cookie,B 让前端读 cookie 塞头
- **跟 [方案 D](./方案D-非对称密钥JWKS.md) 的关系**:D 是 B 的"对称密钥升级到非对称"版,密钥分发安全性更强
- **跟 [方案 F](./方案F-OAuth2授权码PKCE.md) 的关系**:F 是 B 的"演进终态"——B 的设计哲学就是 OAuth2 access token 的简化版
