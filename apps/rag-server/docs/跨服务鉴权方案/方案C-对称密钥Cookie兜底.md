# 方案 C:对称密钥 + Cookie 兜底

> 返回 [索引](./跨服务鉴权方案分析.md)
> 横向跳转:[A](./方案A-独立账号.md) · [B](./方案B-对称密钥前端持JWT.md) · **C** · [D](./方案D-非对称密钥JWKS.md) · [E](./方案E-TokenExchange.md) · [F](./方案F-OAuth2授权码PKCE.md) · [G](./方案G-BFF会话.md) · [H](./方案H-API网关验签.md)

---

## 1. 一句话定位

**让 agent-server 既能从 `Authorization` 头读 JWT,也能从浏览器 cookie 读 JWT**,两个来源都试一下,任一通过都算认证成功。

代价是 agent-server 内部多支持一种"放 token 的位置",并把 cookie 鉴权所有附带的复杂度(CSRF / SameSite / 跨域 cookie)都背上。

```
登录:
  Browser ←─Set-Cookie: agent_jwt=...(HttpOnly, Secure, SameSite=Lax)
                                  ↓
                          浏览器自动存 cookie

之后任何调 agent-server:
  Browser ──Cookie: agent_jwt=...──→ agent-server
                                       ↓
                                JwtStrategy 从 cookie 取 → verify
```

## 2. 概念扫盲:extractor 是什么

`passport-jwt`(Nest `@nestjs/passport` 的 JwtStrategy 底层库)对"JWT 可能藏在哪里"做了一层抽象——**extractor 就是一个"从 request 里把 token 字符串挖出来"的函数**:

```ts
type JwtFromRequestFunction = (req: Request) => string | null;
```

- 输入:整个 HTTP 请求对象
- 输出:JWT 字符串(找到了)或 `null`(没找到)

库自带几个开箱即用的:

| Extractor | 看哪里 |
|---|---|
| `fromAuthHeaderAsBearerToken()` | `Authorization: Bearer <token>` 头 |
| `fromHeader('x-access-token')` | 自定义头 |
| `fromUrlQueryParameter('token')` | `?token=xxx` query 参数 |
| `fromBodyField('access_token')` | 请求体某字段 |

**cookie 不在库自带的里**,因为标准 OAuth2 不鼓励把 token 放 cookie——所以需要自己写一个 cookie extractor:

```ts
const cookieExtractor = (req: Request): string | null => {
  return req.cookies?.['agent_jwt'] ?? null;
};
```

就五行——从请求的 cookies 里把名叫 `agent_jwt` 的取出来。

> 注:NestJS 默认不解析 cookie,需要装 `cookie-parser` 中间件,`app.use(cookieParser())`,`req.cookies` 才会有东西。

## 3. "优先头、回退 cookie" 实际工作流程

`passport-jwt` 提供了 `ExtractJwt.fromExtractors([...])` 工厂,**把多个 extractor 串起来,按数组顺序逐个尝试,第一个返回非 null 的就用**:

```ts
import { ExtractJwt, Strategy } from 'passport-jwt';

super({
  jwtFromRequest: ExtractJwt.fromExtractors([
    ExtractJwt.fromAuthHeaderAsBearerToken(),  // ① 先看 Authorization 头
    cookieExtractor,                           // ② 头里没有再看 cookie
  ]),
  secretOrKey: process.env.JWT_SECRET,
});
```

执行顺序(简化伪代码):

```
Client 发请求
    ↓
JwtStrategy.authenticate()
    ↓
for (extractor of extractors) {
  token = extractor(req)
  if (token != null) break   ◄── 一旦拿到就跳出,不试后面的
}
    ↓
拿到 token? → 否 → 401
    ↓ 是
verify(token, JWT_SECRET) ── 验签 + 验 exp/aud/iss
    ↓
成功 → req.user = payload
失败 → 401
```

**关键点**:验证逻辑(secret、algorithm、过期检查)只有一份——不管 token 来自哪个 extractor,验签代码完全一样。extractor 只决定"从哪里捞这个字符串",**捞到后大家都走同一条验签管道**。

## 4. 两种客户端各自走哪条路

### 4.1 浏览器(走 cookie 路径)

```
登录:
  Browser ──POST /api/login──→ our-chat 后端
          ←──Set-Cookie: agent_jwt=eyJhbGc...; HttpOnly; SameSite=Lax──

之后任何调 agent-server 的请求:
  Browser ──Cookie: agent_jwt=eyJhbGc...──→ agent-server
            (浏览器自动加上,前端 JS 啥也不用写)
                    ↓
            headerExtractor(req)
              → req.headers.authorization 不存在 → null
            cookieExtractor(req)
              → req.cookies.agent_jwt 存在 → 返回 token
                    ↓
            verify → 通过 → req.user = { userId: 42, ... }
```

**前端零代码改动**——浏览器规则:cookie 是哪个域设的,之后调这个域就会自动带回去。

### 4.2 Flutter / curl(走 Authorization 头路径)

Flutter dio / OkHttp / curl 都**没有 cookie 容器**,永远不会自动带 cookie,只能手动塞头:

```bash
curl -H "Authorization: Bearer eyJhbGc..." https://agent-server.com/conversations
```

agent-server 收到:

```
headerExtractor(req)
  → req.headers.authorization = "Bearer eyJhbGc..."
  → 提取出 "eyJhbGc..." → 返回 token   ◄── 第①步就拿到了,根本不试 ②
        ↓
verify → 通过
```

**Authorization 头比 cookie 优先**,所以 Flutter 跑的还是原来的 Bearer 路径,完全不受 cookie extractor 添加的影响。

### 4.3 "兜底" 这个词的含义

- `fromAuthHeaderAsBearerToken()` 排在 ① 位 = **默认所有客户端都该用头**
- `cookieExtractor` 排在 ② 位 = **只有头里没有时才看 cookie**

这有个微妙的工程意义:如果浏览器 SPA 同时手动塞了 Authorization 头(比如前端选择不走 cookie 而是自己读 localStorage 塞头),那 cookie 就被忽略——**头优先生效**。这给了客户端"自由选择鉴权方式"的余地。

## 5. 实现路径汇总

**agent-server**(JwtStrategy 改 5 行,见上 §3):

```ts
const cookieExtractor = (req: Request) => req.cookies?.['agent_jwt'] ?? null;

super({
  jwtFromRequest: ExtractJwt.fromExtractors([
    ExtractJwt.fromAuthHeaderAsBearerToken(),
    cookieExtractor,
  ]),
  secretOrKey: process.env.JWT_SECRET,
});
```

**our-chat 后端**:跟方案 B 几乎一样,但 cookie 可以 HttpOnly(更安全)。

**前端**:啥也不写,浏览器自动带 cookie。

## 6. 这套设计的历史初衷

`passport-jwt` 加 `fromExtractors`(多 extractor 串行)历史上主要为了两个场景:

1. **新旧 API 兼容期**:旧客户端可能还在用 `?token=xxx` query,新的用 Authorization 头,服务端两种都接受,平滑迁移
2. **浏览器友好 + API 友好兼顾**:浏览器懒得管 token(用 cookie),CLI / SDK 走标准 Bearer

方案 C 就是把"浏览器懒得管 token"这条路打开。**但要警惕**:本来 `fromExtractors` 的设计意图是过渡 / 共存,不是"长期主义"——长期上服务应该只接受一条标准路径。

## 7. 部署拓扑硬约束

这是 C 方案的真正成本——必须满足下列**之一**:

| 拓扑 | Cookie 配置 | 备注 |
|---|---|---|
| 同根域(`chat.x.com` + `ai.x.com`) | `domain=.x.com; SameSite=Lax` | 最干净,推荐 |
| 完全同 origin(走反向代理) | 默认 | 最稳,但部署复杂 |
| 跨根域 | `SameSite=None; Secure` + agent-server CORS `Access-Control-Allow-Credentials: true` + 精确 origin(不能 `*`) | Safari ITP 可能拦,Chrome 第三方 cookie 已开始 phase out |

**生产部署在不同云上 → C 方案会翻车。**

## 8. 优劣

| 优 | 劣 |
|---|---|
| 浏览器友好(无前端代码),HttpOnly 抗 XSS | **agent-server 契约污染**:同时维护两条鉴权路径,测试 / 文档 / 监控都要双倍覆盖 |
| 复用 our-chat 已有的 refresh 拦截器 | **绑定部署拓扑**(同根域 / 严格 CORS) |
| GET SSE 可用原生 EventSource(cookie 自动带) | Flutter / curl 走 Bearer 路径,**cookie 路径对它们完全空跑** |
| | 需要 CSRF 防御(因为 cookie 自动带,把 our-chat 已有的 X-CSRF-Token 那套照抄一份) |

## 9. 适用 / 不适用

**适用**:
- 同一组织所有服务都部署在同根域下(典型企业内部门户)
- Web 是唯一/主要客户端,Native 是次要
- 跨服务调用频繁,希望 401 refresh 完全无感

**不适用**:
- agent-server 设计为"多端独立消费"的纯后端 ← **这就是本项目的情况**
- 部署拓扑不能保证同根域
- 团队对 Cookie 安全(CSRF / SameSite Chrome 政策)经验不足

---

## 横向关联

- **跟 [方案 B](./方案B-对称密钥前端持JWT.md) 的关系**:同样共享密钥,但 C 让 agent-server 直接读 cookie,B 让前端读 cookie 塞头。**C 的代价是污染 agent-server 契约**
- **跟 [方案 D](./方案D-非对称密钥JWKS.md) 的关系**:正交——D 改的是签名算法,C 改的是 token 传递载体,可叠加
- **跟 [方案 G](./方案G-BFF会话.md) 的关系**:G 的 BFF 跟 SPA 之间也是 HttpOnly cookie,但是是 BFF 自家发的 session cookie,跟"agent-server 直接接受 cookie"的 C 完全是两件事
