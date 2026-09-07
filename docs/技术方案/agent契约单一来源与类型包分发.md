# agent 契约：单一来源 + 类型包分发

> 面向零项目背景读者。先读术语表，再读正文；所有专业名词首次出现即在同句给大白话解释。

---

## 术语表（先看这个）

| 名词 | 大白话解释 |
|---|---|
| **契约（contract）** | 服务端和调用端之间约好的数据长什么样：有哪些字段、什么类型。比如"一次 agent 运行"有 `runId`(字符串)、`status`(字符串)。约好了双方才不会各说各话。 |
| **proto / Protobuf** | Google 的一种"用文本描述数据结构"的语言，写在 `.proto` 文件里。它**与编程语言无关**——同一份 `.proto` 能生成 TypeScript、Go、Python、Swift 的类型代码。 |
| **IDL** | Interface Definition Language，接口定义语言。proto 就是一种 IDL。 |
| **buf** | 操作 proto 的工具。`buf lint` 查规范、`buf breaking` 查"这次改动会不会破坏老调用方"、`buf generate` 按配置把 proto 生成各语言代码。 |
| **ts-proto** | buf 用的一个插件，把 proto 生成 **TypeScript** 类型。我们开了 `onlyTypes`（只生成类型接口，不生成运行时编解码代码，因为我们走 JSON/REST 不走 protobuf 二进制）。 |
| **生成物（generated code / gen）** | 由 proto 自动生成的代码，**不手写、不手改**。改了要重新 `buf generate`。 |
| **契约漂移（drift）** | 服务端改了契约，但某个调用方还拿着老版本，两边对不上。本方案要消灭的核心问题。 |
| **source of truth（单一权威来源）** | 一份数据/定义只有一个"正版出处"，其余都是它的副本或派生物。避免"多份都能改、改了不同步"。 |
| **npm 包 / 包（package）** | 一坨可被 `npm install` 安装复用的代码，有名字（如 `@talqora/agent-contracts`）和版本号。 |
| **scope（作用域）** | npm 包名 `@xxx/yyy` 里的 `@xxx`，通常代表组织。私有包常用 scope 归属组织。 |
| **registry（仓库源）** | npm 包的托管服务器。公共的是 npmjs.org；本方案私有包发到 **GitHub Packages**（`npm.pkg.github.com`）。 |
| **GitHub Packages** | GitHub 自带的包托管，能存私有 npm 包。用仓库自带的 `GITHUB_TOKEN` 就能发布，但要求**包 scope 等于仓库 owner 登录名**。 |
| **BSR（Buf Schema Registry）** | buf 官方的"proto 云仓库"，可把 proto 模块发上去供跨仓库依赖。本方案的备选方案之一。 |
| **CI** | Continuous Integration，持续集成。代码推上去后自动跑的检查/构建流水线（这里用 GitHub Actions）。 |
| **BFF** | Backend For Frontend，为前端服务的后端。这里指 our-chat 的 server 帮 web 铸 agent-server 用的登录 token。 |

---

## 一、为什么要做这件事（问题）

`agent-server` 是一个**可被多个项目复用**的服务：它提供 RAG（检索增强生成：先从你上传的知识库里检索相关片段，再让大模型据此回答）+ Agent 任务编排。今天接它的是 `our-chat` 的 web 端，明天可能是别的项目。

它对外的数据长什么样，由一份 proto 契约定义：`ourchat.agent.v1`（`AgentRun`、`Citation`、`AgentTaskSession` 等）。

改造前的现状有三个具体毛病（都不是假设，是查代码查出来的事实）：

1. **契约被复制成两份、靠人肉同步。**
   `agent.proto` 原本挂在 **our-chat** 仓库的 `proto/` 下，agent-server 里是**复制**的一份。git 历史里三次改动的 commit message 都写着"与 our-chat 同步"——也就是说人已经手动同步过三次。谁忘一次，两仓就漂移。

2. **生成了三份、只有一处真在用。**
   our-chat 的 `buf.gen.yaml` 把 agent 域生成进 **server / web / gateway** 三个目标。但实测：
   - `server`：**零** import（生成了没人用）；
   - `gateway`：**零** import（同上）；
   - `web`：唯一真正的消费者，`agentView/type.ts` 从生成类型里成批引入 **11 个**类型（`AgentUser`/`AgentRun`/`AgentTaskSession`…）。
   而 web 是**直连** agent-server 的（走 `VITE_AGENT_API_BASE`，JSON/REST + SSE），不经过 our-chat 的 server 转发。

3. **agent-server 自己的生成物是过期的、且没有 CI 兜底。**
   agent-server 的 `apps/node-server/src/contracts/gen` 里，proto 早已有的 `task` 字段和整个 `AgentTaskSession` 消息**都没生成进去**——改了 proto 没重新生成。agent-server 当时只有 `deploy.yml`，**没有 proto 校验 CI**，所以这种漂移没人拦。

一句话概括：**契约的权威归属错了**。它挂在一个"消费方"（our-chat）仓库里，真正的"生产方"（agent-server）反而拿的是复制品；而且没有任何自动化防止漂移。

---

## 二、目标与成功标准

把 agent 契约的权威收归**生产方 agent-server**，让所有消费方从它这里拿，且用自动化防漂移。可验证的成功标准：

- [x] agent 契约的 proto 只在 agent-server 存在一份（our-chat 不再有副本）。
- [x] our-chat 三端不再生成 agent 代码（server/gateway/web 的 agent gen 全删；`google/protobuf` 因 message/presence 仍用而保留）。
- [x] web 改为消费 agent-server 发布的类型包 `@talqora/agent-contracts`，`tsc -b` 与 agentView 测试全绿。
- [x] agent-server 补齐 proto CI（lint + breaking + 生成物新鲜度），并有发布类型包的 CI。
- [x] our-chat 的 server（TS）、gateway（Go）删除 agent 后仍编译通过。

---

## 三、关键设计决策与方案对比

### 决策 1：权威用什么格式？→ proto（保持现状）

agent-server 已用 proto，web/node-server 都消费其 ts-proto 产物。且未来消费方会有**多语言**（Go/Swift/Python）。proto 天生语言无关，是多语言契约的标准解。故不改格式。

> 备注：agent-server 对外是 **JSON/REST + SSE**，proto 在这里只用来**定义 DTO 类型**（`onlyTypes`），不做 protobuf 二进制传输。若将来要给 REST 消费方更贴合的契约，可再叠加 OpenAPI（our-chat 的 mobile-swift 已有 OpenAPI 管线），proto 仍是类型权威。

### 决策 2：契约怎么分发给消费方？

| 维度 | ①发 npm 类型包（选定） | ②buf BSR 远程模块 | ③git submodule 引 proto |
|---|---|---|---|
| 机制 | proto→TS 类型打成 `@talqora/agent-contracts` 发到 GitHub Packages，消费方 `install` | proto push 到 buf.build，消费方 `buf.yaml` 加依赖后本地 `buf generate` | 消费方把 agent-server/proto 作为子模块，本地生成 |
| TS 消费方接入成本 | **最低**：装个包即可，不需 buf/proto 工具链 | 中：每个消费方都要装 buf + ts-proto | 中：同左，且要维护 submodule |
| 多语言消费方 | 需另发对应语言产物（Go/Swift 各自从**同一 proto**生成） | 原生支持：各语言各自 generate | 原生支持 |
| 额外基础设施 | GitHub Packages（GitHub 自带，私有免费） | 需 BSR 账号/组织（私有付费） | 无 registry，但 submodule 体验差 |
| 防漂移 | 版本号（semver）+ CI | BSR 版本 + breaking 检查 | 靠 submodule commit 指针，易忘更新 |
| 业界主流度 | 高（"JS 服务对外暴露客户端 SDK/类型"的标准做法） | 中（buf 生态内） | 低 |

**选 ①**，理由：当下唯一消费方 web 是 TS，npm 包接入成本最低、最主流；GitHub Packages 是 GitHub 自带、私有包免费，不引入额外付费设施。

**但必须点破一个常见误解**：npm 包**只对 TS/JS 消费方成立**，它不是"唯一权威"。既然未来有 Go/Swift/Python，权威必须是**语言无关的 proto**；npm 包只是 proto **面向 TS 消费方的产物之一**。Go 消费方将来从同一份 proto 生成 Go，Swift 走 OpenAPI，各生成各的，互不依赖这个 npm 包。这样"发 npm 包"和"多语言"两个诉求不打架。

### 决策 3：node-server 自己怎么办？（不动 Docker 构建的取舍）

node-server 也消费契约（`chat.service.ts` import 了 `Citation`）。理想的"最佳实践"是把 agent-server 改成 npm workspace，让 node-server 像外部消费方一样依赖本地 `packages/agent-contracts`（dogfooding）。**但**这会改动 Docker 构建上下文（compose 里 `build.context: ../apps/node-server`）、Dockerfile 的 COPY 路径与安装语义——风险外溢到生产部署。

按"能小改不大改、外科手术式改动"的原则，**当前不改 workspace**：让 `buf generate` 同时输出两份——`apps/node-server/src/contracts/gen`（node-server 内部自用，打进镜像、构建零外部依赖）和 `packages/agent-contracts/src/gen`（对外发布）。两份**同一次 generate、同插件同版本，字节一致**，由新加的 freshness CI 保证不漂移。

> 代价：agent-server 仓库内有两份内容相同的生成物。这是刻意的权衡——换取 node-server 生产构建**零改动**。workspace 化 dogfooding 列为"未来可选改进"（见第七节），不在本次范围。

---

## 四、最终架构

```
                权威（唯一来源，语言无关）
        agent-server/proto/ourchat/agent/v1/agent.proto
                          │  buf generate（ts-proto, onlyTypes, 钉 v2.11.8）
          ┌───────────────┴───────────────┐
          ▼                               ▼
 apps/node-server/src/contracts/gen   packages/agent-contracts/src/gen
   （内部自用，打进镜像）                 （对外发布产物）
                                              │  tsc build + npm publish
                                              ▼
                                 GitHub Packages: @talqora/agent-contracts@x.y.z
                                              │  install
                          ┌───────────────────┼───────────────────┐
                          ▼                   ▼                   ▼
                   our-chat/web         未来 TS 项目          （Go/Swift/Python
               agentView/type.ts                             从同一 proto 各自生成，
                                                              不经此 npm 包）
```

防漂移由两条 CI 守住：
- `proto.yml`：`buf lint` + `buf breaking`（对 main 基线）+ **生成物新鲜度**（`buf generate` 后 `git diff --exit-code`，两份 gen 都查）。
- `publish-contracts.yml`：push main 且版本未发布过时，发布类型包到 GitHub Packages。

---

## 五、本次改动清单（两仓）

### agent-server（生产方，分支 `feat/agent-contract-ownership`）
- `buf.gen.yaml`：新增第二个 ts-proto 输出 → `packages/agent-contracts/src/gen`；两个输出都钉 `stephenh-ts-proto:v2.11.8`（与 our-chat 一致、可复现）。
- 新增 `packages/agent-contracts/`：`package.json`（name `@talqora/agent-contracts`、`publishConfig.registry` 指 GitHub Packages）、`tsconfig.json`、`src/index.ts`（re-export gen）、`README.md`、`.gitignore`、`src/gen/**`（buf 生成）。
- `apps/node-server/src/contracts/gen`：因重新生成，**补齐**了此前缺失的 `task` 字段与 `AgentTaskSession`（修既有陈旧，非行为改动；node-server 仅用 `Citation`，新增类型不影响运行时）。
- 新增 `.github/workflows/proto.yml`、`.github/workflows/publish-contracts.yml`。

### our-chat（消费方，分支 `feat/agent-contract-ownership`）
- 删除 `proto/ourchat/agent/`。
- 删除三端 agent 生成物：`server/src/contracts/gen/ourchat/agent/`、`web/src/contracts/gen/ourchat/agent/`、`gateway/internal/contracts/gen/ourchat/agent/`（`google/protobuf/` 保留——message 用 `Struct`、presence 用 `Timestamp`）。
- web：
  - `src/views/agentView/type.ts`：import 从本地 gen 改为 `@talqora/agent-contracts`。
  - `package.json`：加依赖 `@talqora/agent-contracts: ^0.1.0`。
  - `.npmrc`（新增）：`@talqora` scope 指向 GitHub Packages，token 走环境变量 `NODE_AUTH_TOKEN`。
  - `Dockerfile`：加 `NODE_AUTH_TOKEN` build-arg，安装前 COPY `.npmrc`。
  - `docker/docker-compose.prod.yml`：web `build.args` 加 `NODE_AUTH_TOKEN`。
- `proto.yml`：**无需改动**（它按 `/gen/**` 通配触发，无 agent 专属引用；删除后 `buf generate` 不再产出 agent，diff 自然干净）。

---

## 六、前置条件与两阶段迁移 runbook

### 命名分层（已定稿）
- **对外品牌** → `talqora`：npm scope/包名 `@talqora/agent-contracts`、GitHub 组织。品牌变了只动这层。
- **代码托管位置** → 跟仓库归属走：Go 模块前缀 `github.com/our-chat/...`（内部私有服务，无人 `go get`，本次不动）。
- **内部技术标识** → 品牌无关、稳定：protobuf 命名空间保持 `ourchat.*`（`ourchat.agent.v1` 等），不随品牌 churn。
  故 proto 包名、`proto/ourchat/...` 路径、`gen/ourchat/...` 生成路径**刻意保留 `ourchat`**，与 npm scope 无关。

### 前置条件
1. **发布身份对 `talqora` 组织有 `packages:write`** —— ✅ **已完成**：两仓已转入 `talqora` 组织
   （`talqora/agent-server`、`talqora/talqora`，后者由原 `our-chat` 改名）。仓库既在组织下，CI 内置
   `GITHUB_TOKEN` 即对本组织 packages 有写权限，**无需额外密钥**即可发布。
   > `publish-contracts.yml` 的 token 仍写成"优先 `PACKAGES_TOKEN`、缺省回退 `GITHUB_TOKEN`"，
   > 是为将来仓库若移出组织时仍能用 PAT 兜底；当前无需配 `PACKAGES_TOKEN`。
2. **消费方读私有包的鉴权**：our-chat 侧构建需能读 `@talqora/agent-contracts`。
   - GitHub Actions 内：用内置 `GITHUB_TOKEN`（同组织、`packages:read`）即可。
   - 服务器本地 docker build（非 Actions）：需一枚对 `talqora` 有 `read:packages` 的 PAT，经
     `NODE_AUTH_TOKEN` build-arg 注入（部署脚本 export → compose → Dockerfile）。

### 迁移必须分两阶段（存在硬顺序依赖）
消费方（our-chat/web）装包，前提是包已发布。所以**不能在一次本地操作里原子完成**——Phase 2 依赖 Phase 1 的发布产物落到 registry。

**Phase 1 — 发布契约包（agent-server）**
```bash
# 在 agent-server，合并 feat/agent-contract-ownership → main（--no-ff，按项目规范）
# push main 触发 publish-contracts.yml：
#   → buf 生成 → tsc build → 探测 0.1.0 未发布 → npm publish 到 GitHub Packages
# 验证：GitHub 仓库 Packages 页出现 @talqora/agent-contracts@0.1.0
```

**Phase 2 — 消费契约包（our-chat）**
```bash
# 前置：本机/CI 已配 NODE_AUTH_TOKEN（read:packages）
cd our-chat/web
export NODE_AUTH_TOKEN=<PAT>
pnpm install                      # 解析 @talqora/agent-contracts@0.1.0，更新 pnpm-lock.yaml
pnpm build                        # tsc -b && vite build，应绿
npm run lint && npm test          # web 完工门禁
# 提交刷新后的 pnpm-lock.yaml；合并 feat/agent-contract-ownership → main（--no-ff）
```

> 说明：our-chat 分支上 `web/package.json` 已声明依赖但 `pnpm-lock.yaml` 尚未包含它——这是 Phase 2 待补步骤（需已发布的包才能锁定版本）。因此 `docker` 构建（`pnpm install --frozen-lockfile`）必须在 Phase 1 发布 + 本地 `pnpm install` 刷新 lock 之后进行。

### 后续改契约的标准流程
```
改 proto → buf generate → bump packages/agent-contracts/package.json version（破坏性=major）
→ 合并 main（proto.yml 校验 lint/breaking/freshness）→ publish-contracts.yml 自动发布
→ 消费方 pnpm up @talqora/agent-contracts
```

---

## 七、风险、边界与未来

- **本地无法完成发布/推送**：发布需凭据 + 推送（对外动作），本次改造把两仓代码 + CI 全部落地并本地验证到"只差 push+publish"，Phase 1/2 的实际发布留给上述 runbook 执行。
- **私有包鉴权扩散到构建链**：web 的本地 dev 与 Docker build 都需 `NODE_AUTH_TOKEN`。已用环境变量 + build-arg 打通，未把 token 写死进任何文件。
- **两份生成物**：agent-server 内 node-server gen 与包 gen 内容相同，由 freshness CI 保证一致；接受此冗余以换 node-server 生产构建零改动。
- **未来可选改进**：
  - agent-server workspace 化，node-server 直接 dogfood `@talqora/agent-contracts`，消除两份生成物（需一并调整 Docker 构建上下文，单独立项）。
  - 出现 Go/Python 消费方时，在 agent-server `buf.gen.yaml` 加对应语言输出；出现 REST-native 多语言消费方时叠加 OpenAPI。
