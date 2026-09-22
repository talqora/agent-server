# 方案 D:非对称密钥 + JWKS

> 返回 [索引](./跨服务鉴权方案分析.md)
> 横向跳转:[A](./方案A-独立账号.md) · [B](./方案B-对称密钥前端持JWT.md) · [C](./方案C-对称密钥Cookie兜底.md) · **D** · [E](./方案E-TokenExchange.md) · [F](./方案F-OAuth2授权码PKCE.md) · [G](./方案G-BFF会话.md) · [H](./方案H-API网关验签.md)

---

## 1. 原理

把方案 B 的对称密钥换成**非对称密钥对**(RS256/ES256):

- our-chat **私钥**签发 JWT
- agent-server 经 HTTP 端点(JWKS, JSON Web Key Set)动态拉取 **公钥** 验证

```
启动 / 首次验证:
  agent-server ──GET https://ourchat.com/.well-known/jwks.json──→ our-chat
              ←──{ keys: [{ kty: 'RSA', n: '...', e: 'AQAB', kid: 'k1', ... }] }──

正常请求:
  Browser ──Authorization: Bearer <JWT, header.kid='k1'>──→ agent-server
                                                              ↓
                                                   按 kid 找公钥 → verify
```

## 2. 比对称密钥强在哪

| 维度 | 对称 HS256(B/C) | 非对称 RS256(D) |
|---|---|---|
| 密钥分发 | secret 必须共享 → 任一服务泄漏 = 全军覆没 | 私钥只在 our-chat,agent-server 只持公钥(泄漏无害) |
| 多服务扩展 | 每新增一个服务都要分发 secret | 新服务直接拉 JWKS 即可,签发方不动 |
| 密钥轮换 | 必须协调全部服务同时换 | 签发方加新 kid 公开,验证方按 kid 选,平滑过渡 |
| 验签性能 | 快(HMAC) | 略慢(RSA / ECDSA),但仍 < 1ms |
| 实现复杂度 | 低 | 中(要起 JWKS 端点 + 实现 caching) |

> **业界共识**:JWT 用对称密钥几乎只在"两端是同一团队、明确不会有更多消费者"时合适。**一旦有第三个服务要验签,立刻切 RS256**。

## 3. 实现路径

**our-chat 后端**:

```ts
// 启动时生成 / 加载 RSA 密钥对
const { publicKey, privateKey } = crypto.generateKeyPairSync('rsa', { ... });

// 签发
const token = jwt.sign(payload, privateKey, {
  algorithm: 'RS256',
  keyid: 'k1',                      // 标识当前用哪把私钥
  expiresIn: '15m',
});

// 暴露 JWKS 端点
app.get('/.well-known/jwks.json', (req, res) => {
  res.json({ keys: [jwkFromPublicKey(publicKey, 'k1')] });
});
```

**agent-server**(用 `jwks-rsa` 库):

```ts
import { passportJwtSecret } from 'jwks-rsa';

super({
  jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
  secretOrKeyProvider: passportJwtSecret({
    jwksUri: 'https://ourchat.com/.well-known/jwks.json',
    cache: true,
    cacheMaxAge: 10 * 60 * 1000,     // 10 min
    rateLimit: true,
  }),
  algorithms: ['RS256'],
});
```

## 4. 踩坑

- **JWKS 拉取失败的兜底**:agent-server 启动时如果 our-chat 不在,验签全失败。必须缓存 + retry + 监控告警
- **kid 选错**:JWT header 必须带 kid,否则验证方不知道用哪个公钥(可能是初始化 bug)
- **密钥轮换时机**:新 kid 公开后,要等所有 in-flight token 过期(token TTL 时间)才能下线旧 kid

## 5. 适用场景

- 中长期项目,可预见会有多个 resource server
- 安全合规要求(SOC 2 / 等保)倾向非对称
- 团队有运维能力维护 JWKS 端点

---

## 横向关联

- **跟 [方案 B](./方案B-对称密钥前端持JWT.md) 的关系**:D 是 B 的"密钥架构升级版"——token 传递载体不变(仍是前端持 JWT 塞头),换的是签名算法和密钥分发方式
- **跟 [方案 F](./方案F-OAuth2授权码PKCE.md) 的关系**:F 用 RS256 + JWKS 是标准配置;D 是 F 的"密钥子系统"被提前用上
- **推荐演进**:B → D 是平滑路径,token 传递逻辑不变,只是签名升级
