# 12 · 深度 · 上行可靠 —— 幂等键、ack、重传、去重

> 对应 [10 目标架构](10-目标架构.md) 的 **INV-2**(同一 `(conv,sender,clientMsgId)` 至多入库一次)与 **INV-3**(先持久化再推送)。
> 上游依赖 [11 会话内单调 seq](11-深度-消息时序与会话内单调seq.md):ack 要回带服务器分配的 seq。
> 主题:从客户端到服务器这一跳,**怎么做到"消息不丢、不重"**。这是 IM 面试的第一深挖点。

---

## 一、背景与动机:为什么消息会丢、会重

### 1.1 先看两个会真实发生的场景

**场景 A(丢)**:
```
客户端发"晚上一起吃饭" → WiFi 切 4G,TCP 连接断 → 消息卡在客户端发送缓冲区 → 没人告诉用户它没到
结果:用户以为发了,对方根本没收到。"消息丢了"。
```

**场景 B(重)**:
```
客户端发"转账成功" → 服务器收到并入库 → 回 ack 的包在路上丢了 → 客户端等不到 ack,超时重发
→ 服务器又收到同一条 → 又入库一次 → 对方看到两条"转账成功"。"消息重了"。
```

注意 B 的吊诡:**正是"为了不丢而重发"这个动作,制造了"重"**。丢和重不是两个独立问题,而是同一个硬币的两面——这正是这一节要解决的张力。

### 1.2 本质:网络是不可靠信道,且"发送方无法区分两种失败"

为什么这么难?因为底层有一个无法绕过的事实:

> **发送方收不到 ack 时,它无法区分到底是"消息没送到"还是"消息送到了但 ack 丢了"。**

```
客户端发消息,然后等 ack……超时了。到底发生了什么?
  情况①:消息根本没到服务器        → 应该重发
  情况②:消息到了、入库了,只是 ack 丢了 → 不该重发(会重复)
客户端从外部看,①和②长得一模一样,无法分辨。
```

这是分布式系统的经典困境(可类比"两将军问题":通过不可靠信道,双方永远无法 100% 确认对方收到了)。既然**无法分辨**,客户端的安全策略只能是"**收不到 ack 就重发**"(宁可重发也不丢)。而一旦会重发,服务器就**必须有能力识别"这条我已经处理过了"**——否则就重复。

**所以可靠投递的设计被逼成一个固定结构:重发(保证不丢)+ 去重(保证不重)。** 这一节剩下的全部内容,都是在把这两件事做扎实。

### 1.3 三种投递语义:为什么"exactly-once"只能是效果而非机制

消息系统的可靠性有三个经典级别,必须能讲清:

| 语义 | 含义 | 怎么实现 | 问题 |
|---|---|---|---|
| **at-most-once(至多一次)** | 发一次,丢了就丢了 | 不重发 | 会丢消息,IM 不可接受 |
| **at-least-once(至少一次)** | 保证到,但可能重复 | 收不到 ack 就重发 | 会重复 |
| **exactly-once(恰好一次)** | 不丢不重 | —— | **在不可靠网络上,纯传输层做不到** |

**关键认知(面试高频)**:理论上,在一个会丢消息的网络里,**纯靠传输无法实现真正的 exactly-once**(因为 §1.2 的不可分辨困境)。工程上能做到的是:

> **at-least-once(重发兜底不丢)+ 接收端幂等(去重不重)= exactly-once 的"效果"。**

也就是说,我们不追求"消息只在网络上传一次"(做不到),而是追求"**无论网络上传了几次,最终入库和呈现都恰好一次**"。把 exactly-once 从"传输保证"降级成"**处理结果保证**",这是整个设计的思想内核。

### 1.4 底层原理:为什么 TCP 的"可靠"救不了你(端到端原则)

新手常有的误区:"我用了 TCP / WebSocket,TCP 不是可靠传输吗,怎么还会丢?"——必须能拆穿这个误区:

- **TCP 的可靠只覆盖"字节从一端内核送到另一端内核"**。它保证字节不丢、不乱序、不重复——**但仅限于这条连接存活期间**。
- TCP **管不了**这些:连接断了重连后那条消息怎么办?字节到了对端内核,但应用进程还没读取就崩了怎么办?应用读了但**写数据库失败**了怎么办?

这就是分布式系统的 **端到端原则(end-to-end argument,Saltzer/Reed/Clark 1984)**:

> **一个功能(这里是"可靠投递")只有在通信的两个端点(应用层)实现才真正可靠;放在中间层(TCP)只是优化,不能替代端到端的保证。**

具体到 IM:"消息可靠送达"的端点是**发送方 App** 和 **服务器的数据库落库**。所以可靠性必须由**应用层的 ack(确认已落库)+ 重传 + 去重**来保证,TCP 的可靠只是顺带帮忙,**绝不能依赖它**。

> 面试杀招:被问"你都用 WebSocket 了为什么还要自己做 ack",答"TCP 只保证字节到内核,不保证应用落库成功;按端到端原则,可靠投递必须在应用层做端到端确认"。这是第三层。

---

## 二、概念与底层原理

### 2.1 ack:应用层的"已落库确认"

ack(acknowledgement)= 服务器告诉客户端"**你这条消息我已经安全落库了**"。

- 注意 ack 的语义边界:**ack = 已持久化,不是"已读"、也不是"已送达对方"**。它只确认"上行这一跳成功了"。
- ack 必须**回带服务器分配的 seq + serverMsgId**(依赖 11):客户端拿到 ack 才知道这条消息的最终身份和顺序,才能把本地"发送中"的临时消息替换成"已发送"的正式消息。
- 类比 TCP 的 ACK:同样是"我收到了,你可以不用重发了"的信号。区别是 TCP ACK 确认"字节进内核",我们的 ack 确认"消息进数据库"——**确认的位置更靠后,所以更可靠**(呼应 §1.4 端到端)。

### 2.2 幂等性:同一操作做几次,结果都一样

**幂等(idempotency)** 的数学定义:`f(f(x)) = f(x)`。工程含义:**一个操作执行一次和执行多次,对系统状态的影响相同。**

- HTTP 里 `GET`/`PUT`/`DELETE` 设计上幂等,`POST` 不幂等(连发两次 POST 会创建两条)。
- "发消息"天然**不幂等**(发两次就两条),我们要做的就是**人为把它改造成幂等**——靠幂等键。

### 2.3 幂等键:让服务器认得出"这是同一条"

**幂等键(idempotency key)= 客户端为每条逻辑消息生成的全局唯一标识(`clientMsgId`,UUIDv4),重发时复用同一个键。**

- 第一次发:服务器没见过这个键 → 处理 + 落库。
- 重发(同一个键):服务器认出"这个键我处理过了" → **不再处理,直接返回首次结果**。

幂等键是把 §1.3 的等式"at-least-once + 幂等 = exactly-once 效果"落地的那个"幂等"。**它是整套可靠性的去重之锚。**

### 2.4 拼起来:上行可靠的完整闭环

```
客户端                                服务器
  │ 生成 clientMsgId(UUID)             │
  │── send(clientMsgId, conv, body) ──►│
  │ 本地存 outbox,标记"发送中"          │ 幂等查重(clientMsgId)
  │                                     │   见过 → 返回首次的 {seq,serverMsgId}
  │                                     │   没见过 → 分配 seq + 落库(同事务,11)
  │◄──── ack(clientMsgId,seq,...) ──────│
  │ 收 ack → outbox 标记"已发送"         │
  │ 超时没收 ack → 重发同一个 clientMsgId │（回到顶部,服务器靠幂等键挡住重复）
```

**三个不变量串起来**:重发保证不丢(at-least-once)→ 幂等键 + 去重保证不重(idempotent)→ 先落库再 ack(INV-3)保证 ack 一定对应已持久化的消息。

---

## 三、现状的坑(基于真实 schema)

现状权威:`our-chat/server/prisma/schema.prisma`。

```prisma
model Message {
  status String @default("sent") @db.VarChar(32)   // 有个状态字段
}
```

- 有 `status='sent'`,但**看不到端到端闭环**:没有 `clientMsgId` 幂等键、没有去重唯一约束、没有 ack 协议、没有重传/超时逻辑、没有客户端 outbox 持久化。
- 后果:**网络抖动重发就会重复入库**;**杀进程重开会丢"发送中"消息**;**ack 语义缺失**导致客户端无法可靠地知道"到底发出去没"。
- 这正是面试官第一个会挖的点:"你的消息会不会丢/重?怎么保证?"——现状答不出闭环。

---

## 四、各方案分析(逐个拆机制 + 失败模式 + 边界)

### 4.1 幂等键放哪?

| 方案 | 做法 | 优点 | 失败模式/边界 |
|---|---|---|---|
| **客户端 UUID(`clientMsgId`,选)** | 客户端生成 UUIDv4,随消息上行,重发复用 | 客户端本地即可生成、无需往返;天然全局唯一 | 依赖客户端正确"重发用同键"(协议约束) |
| 业务字段组合做键 | 如 `(senderId, content, 粗时间窗)` | 不需客户端配合 | **会误判**:同一句"在吗"正常发两次会被当重复吞掉;时间窗难定 |
| 服务器纯序号 | 服务器收到才发号 | 服务器可控 | **解决不了重发去重**:重发时服务器还没法认出是同一条(它每次都发新号) |

**选客户端 UUID**:幂等键必须**在客户端生成**,因为只有客户端知道"这次重发和上次是同一条逻辑消息"。服务器侧无法仅凭内容判断"用户是手抖发了两次,还是网络重发了一次"。

### 4.2 去重怎么落地?(三种,本项目用唯一约束)

| 方案 | 机制 | 并发安全 | 失败模式 |
|---|---|---|---|
| **DB 唯一约束(选)** | `UNIQUE(conv,sender,clientMsgId)`,重复 INSERT 撞约束 | ✅ **数据库层强制**,并发下也不可能两条都进 | 需捕获冲突错误并返回首次结果 |
| 先查再插(check-then-insert) | 先 SELECT 有没有,没有才 INSERT | ❌ **有竞态**:两个并发重发同时 SELECT 都没查到,然后都 INSERT → 两条 | 高并发下漏判 |
| Redis SETNX 占位 | 用 Redis `SET key NX` 抢占幂等键 | ⚠️ 快,但 Redis 与 DB **两套真相**,要处理"Redis 占了但 DB 落库失败" | 一致性边界复杂,且 Redis 丢键就失效 |

**选唯一约束**,核心理由:**把去重下沉到数据库的强一致约束**,无论多少并发重发,DB 保证最多一条进。`先查再插`看似直觉但**有致命竞态**(这是面试常考的"check-then-act race"),Redis SETNX 引入双真相。唯一约束最简单且**正确性最强**。

> 注意:唯一约束 + §六的"捕获冲突返回首次结果"必须配套。光有约束、冲突时直接报错给用户,体验也是坏的。

### 4.3 ack 的时机:落库前 ack 还是落库后 ack?

这条直接由 **INV-3** 决定,但要讲清代价:

| 时机 | 后果 |
|---|---|
| **落库成功后才 ack(选)** | ack 一定对应一条已持久化的消息。客户端收到 ack = 真的安全了 |
| 收到就 ack(落库前) | 若随后落库失败,客户端以为成功了不再重发 → **真丢**。违反"先持久化再推送" |

**必须落库后 ack**。这意味着 ack 里能顺带回带"落库时分配的 seq",一举两得。

### 4.4 重传策略:超时与退避

- **超时**:发出后启动定时器,超时未收 ack 则重发(同 clientMsgId)。
- **退避(backoff)**:连续失败时,重发间隔**指数增长**(如 1s→2s→4s,带随机抖动 jitter),避免网络抖动期所有客户端同时重发把服务器打垮(惊群)。
- **上限**:重发 N 次仍失败,标记"发送失败"让用户手动重试,不无限重发耗电。
- 这套和 TCP 的超时重传 + 拥塞退避是同构思想,可类比。

### 4.5 发送中状态放哪?(outbox 模式)

"发送中"的消息必须**持久化到客户端本地**(IndexedDB / sqlite),不能只放内存:

- 不持久化的代价:**杀进程/崩溃重开,"发送中"消息凭空消失**,用户以为发了其实没发(回到 §1.1 场景 A)。
- **本地 outbox(发件箱)模式**:消息先写本地 outbox(状态=发送中)→ 上行 → 收 ack 后从 outbox 移除(或标记已发送)。App 重启时扫描 outbox,把还在"发送中"的重发一遍。**这是客户端侧不丢的关键**,常被忽略。

---

## 五、核心机制:唯一约束在并发重发下怎么兜底

把 §4.2 选的方案讲到机制级。关键场景:**两个重发包几乎同时到达**(客户端超时重发,但原包其实只是慢,没丢)。

```
重发包 R1 ─┐
            ├─ 几乎同时到服务器(可能落在不同副本/不同连接)
重发包 R2 ─┘

R1 事务: INSERT messages(...clientMsgId=X)  → 拿到唯一约束,成功
R2 事务: INSERT messages(...clientMsgId=X)  → 撞 UNIQUE(conv,sender,clientMsgId)
          → PG 抛 unique_violation(SQLSTATE 23505)
          → 应用捕获 → SELECT 出已存在那条 → 返回它的 {seq,serverMsgId} 作为 ack
```

机制要点:
- **唯一索引是在数据库引擎层强制的**。即使 `先查再插` 的 SELECT 阶段两个事务都没查到(竞态),**INSERT 阶段也只有一个能成功**,另一个必然撞约束。这就是为什么唯一约束比应用层 check 强。
- 捕获 `23505` 后**不能把错误抛给用户**——这是正常的去重路径,要转成"返回首次结果"。两次 ack 回带的 seq/serverMsgId **完全一致**,客户端收到任意一个都正确收敛。
- 因此即使消息被处理"两次"(两个事务都跑了),**入库恰好一次**,呈现恰好一次——§1.3 的"exactly-once 效果"在此兑现。

---

## 六、关键实现

### 6.1 Schema(幂等键 + 唯一约束,已在 11 §6.1 一并加)

```prisma
model Message {
  clientMsgId String? @map("client_msg_id") @db.VarChar(64)
  @@unique([conversationId, senderId, clientMsgId], map: "uniq_msg_idem")
}
```

> 为什么键是 `(conv, sender, clientMsgId)` 而不只 `clientMsgId`:① 防止不同用户/会话 UUID 万一碰撞;② 索引按会话/发送者聚簇,查重命中更快。

### 6.2 服务器:落库 + 幂等 + ack(Node)

```ts
async function handleSend(input: {
  conversationId: string; senderId: bigint; content: string; clientMsgId: string;
}) {
  try {
    // persistMessage 内部:幂等查重 → 同事务拿 seq + 落库(见 11 §6.2)
    const { message, deduped } = await persistMessage(input);
    // 落库成功后才 ack(INV-3 / §4.3),回带 seq
    return ack({ clientMsgId: input.clientMsgId, seq: message.seq, serverMsgId: message.id });
  } catch (e) {
    // 并发重发撞唯一约束(§五):取出首次结果返回,不报错(§4.2)
    if (isUniqueViolation(e)) {                       // PG SQLSTATE 23505
      const existed = await prisma.message.findUnique({
        where: { uniq_msg_idem: {
          conversationId: input.conversationId, senderId: input.senderId, clientMsgId: input.clientMsgId,
        }},
      });
      return ack({ clientMsgId: input.clientMsgId, seq: existed!.seq, serverMsgId: existed!.id });
    }
    throw e;  // 真异常才上抛,不沉默(CLAUDE.md:async 必须有 error 路径)
  }
}
```

### 6.3 客户端:outbox + 重传(伪代码)

```ts
async function sendMessage(conv: string, body: string) {
  const clientMsgId = uuidv4();
  await outbox.put({ clientMsgId, conv, body, status: 'sending' }); // ① 先持久化到本地(§4.5)
  trySend(clientMsgId);
}

function trySend(clientMsgId: string, attempt = 0) {
  const msg = outbox.get(clientMsgId);
  socket.emit('message.send', { clientMsgId: msg.clientMsgId, conversationId: msg.conv, body: msg.body });
  // 超时未收 ack → 指数退避重发同一个 clientMsgId(§4.4)
  const timer = setTimeout(() => {
    if (attempt < MAX_RETRY) trySend(clientMsgId, attempt + 1);
    else outbox.update(clientMsgId, { status: 'failed' });        // 标记失败,让用户手动重试
  }, backoff(attempt));                                            // 1s,2s,4s + jitter
  ackWaiters.set(clientMsgId, timer);
}

socket.on('message.ack', ({ clientMsgId, seq, serverMsgId }) => {
  clearTimeout(ackWaiters.get(clientMsgId));
  outbox.update(clientMsgId, { status: 'sent', seq, serverMsgId }); // ② 收 ack 才落定
});

// App 启动:扫描 outbox,把"发送中"的重发(§4.5,崩溃恢复不丢)
onAppStart(() => outbox.findByStatus('sending').forEach(m => trySend(m.clientMsgId)));
```

---

## 七、踩坑案例(真实可复现)

### 坑 1:用"先查再插"去重 → 并发重发漏判
**复现**:去重逻辑写成 `if (!await find(clientMsgId)) await insert(...)`。压测时同一 clientMsgId 并发两次,两个请求的 `find` 都返回空,然后都 `insert` → 两条。**根因**:check-then-act 竞态。**修复**:改唯一约束(§4.2、§五)。

### 坑 2:撞唯一约束直接把错误抛给用户
**复现**:加了唯一约束但没捕获 `23505`,正常重发(网络抖动)时用户看到"发送失败:duplicate key"。**根因**:把"正常去重"当成了"异常"。**修复**:捕获冲突 → 返回首次结果当 ack(§6.2)。

### 坑 3:落库前就 ack
**复现**:为了"快",收到消息立刻 ack,再异步落库;某次落库失败 → 客户端已收 ack 不再重发 → 消息真丢。**根因**:违反 INV-3。**修复**:落库成功后才 ack(§4.3)。

### 坑 4:发送中状态只在内存
**复现**:正在转圈"发送中"时杀掉 App,重开后这条消息消失。**根因**:没持久化 outbox。**修复**:发送前先写本地 outbox,启动时扫描重发(§4.5、§6.3)。

### 坑 5:无退避的重传 → 抖动期惊群
**复现**:固定 500ms 重发,网络抖动 10s 期间,海量客户端每 500ms 齐刷刷重发,服务器恢复瞬间被打垮。**根因**:无退避 + 无 jitter。**修复**:指数退避 + 随机抖动(§4.4)。

### 坑 6:clientMsgId 每次重发都重新生成
**复现**:重发时图省事又 `uuidv4()` 了一个新键 → 服务器认不出是同一条 → 去重失效 → 重复。**根因**:幂等键的前提是"重发复用同键"。**修复**:键随 outbox 持久化,重发读旧键(§6.3)。

---

## 八、Web vs Native 视角

| 维度 | Web(React) | Flutter | 原生 Swift |
|---|---|---|---|
| outbox 持久化 | IndexedDB(注意配额、隐私模式禁写) | sqflite/Drift,稳定 | Core Data/SQLite,稳定 |
| 重传定时器 | `setTimeout`;**页面隐藏/息屏时定时器被节流甚至暂停**,回前台要补发 | 后台被挂起,恢复时扫 outbox | 后台挂起最激进,**必须**靠启动扫描 outbox 兜底 |
| UUID 生成 | `crypto.randomUUID()`(需 HTTPS/安全上下文) | `Uuid()` 包 | `UUID()` 原生 |
| 进程被杀 | 刷新/关标签 = 进程没了,内存态全失 → outbox 必须落 IndexedDB | 系统回收 | 系统回收 |

> **Web 的真坑**:浏览器后台标签页会**节流/暂停定时器**(为省电),导致重传定时器不按时触发;且隐私模式下 IndexedDB 可能不可写。所以 Web 端"启动/可见性恢复时扫 outbox 重发"比定时器更可靠。原生靠后台挂起恢复钩子。**三端都不能只依赖定时器,必须有"启动/恢复时对账 outbox"兜底。**

---

## 九、自检与面试问答

### 9.1 自检清单
- [ ] 能解释"丢和重是同一枚硬币":因为发送方无法区分"消息没到"和"ack 丢了",只能重发,于是必须去重
- [ ] 能讲清三种投递语义,以及"exactly-once 是处理结果保证(at-least-once + 幂等),不是传输保证"
- [ ] 能用端到端原则解释"为什么 TCP 可靠还不够,必须应用层 ack"
- [ ] 能解释幂等键为什么必须客户端生成
- [ ] 能讲清"先查再插"的竞态,以及唯一约束为什么能在并发下兜底(机制级)
- [ ] 能解释为什么必须落库后才 ack
- [ ] 能讲 outbox 持久化 + 启动重发为什么是客户端不丢的关键

### 9.2 面试深挖剧本

| 面试官问 | 你的答案锚点 |
|---|---|
| 你的消息会不会丢、会不会重?怎么保证? | 重发保证不丢 + 幂等键去重保证不重,先落库后 ack(§二闭环) |
| 既然要重发,怎么不重复? | 客户端 clientMsgId 幂等键 + DB 唯一约束,重复 INSERT 撞约束返首次结果(§4.2、§五) |
| 你都用 WebSocket 了,TCP 不是可靠的吗? | TCP 只保证字节到内核,不保证落库;端到端原则要求应用层做 ack(§1.4) |
| exactly-once 能做到吗? | 纯传输做不到;at-least-once + 幂等 = exactly-once 效果(§1.3) |
| 幂等键为什么放客户端? | 只有客户端知道"这次重发和上次是同一条逻辑消息"(§4.1) |
| 用"先查再有就不插"行不行? | 有 check-then-act 竞态,并发重发会漏判;必须唯一约束(§4.2) |
| ack 在落库前发还是后发? | 必须落库后,否则落库失败客户端不重发会真丢(§4.3) |
| App 崩了"发送中"的消息怎么办? | outbox 持久化本地,启动扫描重发(§4.5) |
| 网络抖动大家一起重发会不会打垮服务器? | 指数退避 + jitter 防惊群(§4.4) |

---

## 十、与其它文档的关系
- 上游:[10](10-目标架构.md) INV-2/INV-3;[11](11-深度-消息时序与会话内单调seq.md)(ack 回带 seq、同事务落库)。
- 下游:[13](13-深度-下行可靠-离线增量补拉.md)(下行用同一套"持久化 + 游标"思想做离线补齐)。
- 理论出处:端到端原则(Saltzer/Reed/Clark, "End-to-End Arguments in System Design", 1984);两将军问题(不可靠信道下的确认不可能性)。
