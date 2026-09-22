# SOP · @talqora/agent-contracts 类型包：发布与消费操作手册

> 面向零背景读者。先读术语表；所有专业名词首次出现即在同句给大白话解释。
> 本文分两部分：**Part 1** 是可照抄的操作步骤（含已完成事项留档），**Part 2** 把 GitHub
> Packages 的完整作用流程与底层原理讲透（"为什么这么做"，不只"怎么做"）。

---

## 术语表（先看这个）

| 名词 | 大白话解释 |
|---|---|
| **契约类型包** | 这里特指 `@talqora/agent-contracts`：把 agent-server 对外数据结构（proto 定义）生成的 TypeScript 类型，打包成一个可 `npm install` 的东西，供前端等消费方装来用。 |
| **registry（仓库源）** | 存放 npm 包的服务器。公共的是 `npmjs.org`；本项目私有包放在 **GitHub Packages**（`npm.pkg.github.com`）。 |
| **GitHub Packages** | GitHub 自带的"包托管服务"，能存 npm/Docker/Maven 等包。用仓库自带的 `GITHUB_TOKEN` 就能在 CI 里发布。 |
| **scope（作用域）** | npm 包名 `@xxx/yyy` 里的 `@xxx`。在 GitHub Packages 里，`@xxx` **必须等于**拥有该包的 GitHub 组织/账号登录名（本项目是组织 `talqora`）。 |
| **.npmrc** | npm/pnpm 的配置文件。这里用它做两件事：把 `@talqora` 作用域指到 GitHub Packages；提供读包用的鉴权 token。 |
| **PAT** | Personal Access Token，个人访问令牌。一串代表"你"的密码式字符串，给脚本/工具用来代表你访问 GitHub。 |
| **`GITHUB_TOKEN`** | GitHub Actions 每次运行**自动**发给该次运行的临时令牌，代表"这个仓库的这次 CI"，用完即失效。 |
| **scope 权限 `read:packages` / `write:packages`** | token 的能力开关：能读私有包 / 能发布包。 |
| **lockfile（`pnpm-lock.yaml`）** | 锁定每个依赖的确切版本与哈希的文件，保证"谁装都装到一模一样的东西"。 |
| **packument** | package + document 的合成词，指 registry 返回的**某个包的元数据 JSON**（有哪些版本、每个版本的 tarball 下载地址与哈希）。 |
| **tarball** | 一个 `.tgz` 压缩包，就是这个包的实际文件内容。 |
| **SRI / integrity** | Subresource Integrity，一段 `sha512-...` 哈希，装包时用来校验下载到的 tarball 没被篡改/损坏。 |

---

# Part 1 · 操作手册

## 1.0 当前状态（哪些已完成，哪些待做）

| 项 | 状态 |
|---|---|
| 两仓转入 `talqora` 组织（`talqora/agent-server`、`talqora/talqora`） | ✅ 已完成 |
| agent 契约收归 agent-server、our-chat 删除副本、web 改消费包 | ✅ 已合并主分支（agent-server `master`、our-chat `main`） |
| CI：`proto.yml`（lint/breaking/freshness）、`publish-contracts.yml` | ✅ 已就绪且跑绿 |
| **首次发布 `@talqora/agent-contracts@0.1.0`** | ✅ **已发布到 GitHub Packages** |
| our-chat/web 的 `pnpm-lock.yaml` 锁定该依赖 | ⏳ **待做（见 1.2，需一枚 read:packages token）** |

## 1.1 首次发布（Phase 1）—— 已完成，留档

已通过 `push master → publish-contracts.yml` 自动完成，无需重做。记录当时链路，供理解与复现：

1. 合并 `feat/agent-contract-ownership → master`（`--no-ff`）。
2. `git push origin master` → 触发 `publish-contracts.yml`：
   - `actions/setup-node`（写好指向 GitHub Packages 的 `~/.npmrc` + 注入 `NODE_AUTH_TOKEN`）
   - `npm install` → `npm run build`（tsc 产 `dist/`）
   - "Detect if version already published"：`npm view @talqora/agent-contracts@0.1.0` 探测 → 未发布 → `publish=true`
   - `npm publish` → 包落到 `https://github.com/orgs/talqora/packages`
3. 因仓库已在 `talqora` 组织下，CI 内置 `GITHUB_TOKEN`（`permissions: packages: write`）即有权发布，**未用额外密钥**。

> 若哪天仓库移出组织，`GITHUB_TOKEN` 就发不到 `talqora` 了；届时在 agent-server 仓库加 Secret
> `PACKAGES_TOKEN`（对 `talqora` 有 `write:packages` 的 PAT）即可，workflow 已写成"优先用它、缺省回退 `GITHUB_TOKEN`"。

## 1.2 消费方接入 / 刷新 lockfile（Phase 2）—— 待做

`web/package.json` 已声明 `@talqora/agent-contracts: ^0.1.0`，但 `pnpm-lock.yaml` 还没锁定它，
`pnpm install --frozen-lockfile`（Docker 构建用）会失败。需要一次带鉴权的 `pnpm install` 把它锁进去。

### 步骤 A · 创建 read:packages Token（约 1 分钟）
1. 打开 **https://github.com/settings/tokens** → Developer settings → Personal access tokens → **Tokens (classic)**。
2. **Generate new token → Generate new token (classic)**。
3. 填写：Note 取 `talqora-packages-read`；Expiration 按需（如 90 天）；**Scope 只勾 `read:packages`**。
4. **Generate token**，复制 `ghp_...`（离开页面就看不到，务必先存好）。

> 为什么要 token：仓库虽 Public，但 GitHub Packages 的 npm 包默认 **private**，安装要鉴权。（想免 token 见 1.2·D）

### 步骤 B · 本地刷新 lockfile 并验证
本地目录名仍是 `our-chat`（remote 指向 `talqora/talqora`）：
```bash
export NODE_AUTH_TOKEN=ghp_你复制的token      # web/.npmrc 用 ${NODE_AUTH_TOKEN} 读它
cd /Users/mac/our-chat/web
pnpm install                                   # 解析 @talqora/agent-contracts@0.1.0 → 写进 pnpm-lock.yaml
pnpm build                                     # tsc -b && vite build，应全绿
```
成功标志：输出含 `+ @talqora/agent-contracts 0.1.0`，且 `git status` 显示 `pnpm-lock.yaml` 变更。

### 步骤 C · 提交并推送
```bash
cd /Users/mac/our-chat
git add web/pnpm-lock.yaml
git commit -m "chore(web): lock @talqora/agent-contracts@0.1.0"
git push origin main
```
至此契约链闭环：agent-server 发布 → web 锁定消费。

### 步骤 D（可选）· 把包设为 Public，以后免 token
1. 打开 **https://github.com/orgs/talqora/packages** → 进入 `agent-contracts`。
2. **Package settings** → **Danger Zone** → **Change visibility** → **Public**。
3. 权衡：公开 = 任何人可看这份类型定义（只有字段结构、无密钥），换取零 token 摩擦；要保密就跳过。

## 1.3 以后"改 agent 契约"的标准流程
```
① 改 agent-server/proto/ourchat/agent/v1/agent.proto
② cd agent-server && buf generate                       # node-server gen 与包 gen 两份一起更新
③ bump packages/agent-contracts/package.json 的 version # 破坏性改动升 major(见语义化版本)
④ git commit && git push origin master                  # proto.yml 校验 + publish-contracts 自动发新版
⑤ 消费方(web): pnpm up @talqora/agent-contracts && 提交 pnpm-lock.yaml
```
> version 不 bump 会怎样：`npm publish` 对已存在版本报错；workflow 里"探测已发布则跳过"，故不 bump 就不会发新内容。

## 1.4 排障速查

| 现象 | 原因 | 处置 |
|---|---|---|
| `pnpm install` 报 **401/403** | token 没勾 `read:packages`，或 `NODE_AUTH_TOKEN` 没 export | `echo $NODE_AUTH_TOKEN` 确认非空；重开 token 勾对 scope |
| CI **publish 没触发** | 推的分支不匹配 `on.push.branches`（agent-server 是 **master** 不是 main） | 确认推到 master；或用 `workflow_dispatch` 手动跑 |
| CI **publish 显示成功但没发新版** | 版本号没 bump，"探测已发布→跳过" | bump `packages/agent-contracts/package.json` 的 version 再推 |
| CI **proto freshness 红**，diff 在 `google/protobuf/*.ts` | `buf-setup-action` 没钉版本，装了新 buf，其内置 well-known types 的 proto 注释漂移 | 已在 `proto.yml` 钉 `buf` 到 `1.71.0`（与 ts-proto 插件钉 v2.11.8 同策略）；换 buf 版本需同步 |
| 消费方 tsc 找不到 `@talqora/agent-contracts` 的类型 | 包没装上（lockfile 未含/未鉴权），或 `.npmrc` 作用域映射缺失 | 完成 1.2；确认 `web/.npmrc` 有 `@talqora:registry=...` |

---

# Part 2 · 深入：GitHub Packages（npm）完整作用流程与底层原理

> 目标：读完你能在脑子里画出"一次 publish 和一次 install 分别向哪台服务器发了什么请求、
> 带了什么头、服务器怎么鉴权、文件存哪"。不靠背命令，靠理解。

## 2.1 它解决什么问题（没有它会怎样）

多个项目要复用 agent-server 的类型。若不发包，每个消费方只能**手抄**一份类型 —— 服务端改了字段、
手抄的忘了改，就是线上 bug（"契约漂移"）。发包解决的是：**一份类型有唯一正版出处、带版本号、可一键安装、
可校验完整性**。GitHub Packages 就是这个"正版出处"的托管服务器；它对 npm 客户端（npm/pnpm/yarn）
**伪装成一个标准 npm registry**，所以你用的还是原来那套 `npm install`，只是包从 GitHub 那台服务器来。

## 2.2 npm registry 到底是什么（协议层）

关键认知：**"npm registry" 不是某个特定网站，而是一套 HTTP 接口约定**。任何服务器只要实现这套约定，
npm 客户端就能把它当 registry 用。npmjs.org、GitHub Packages、私有的 Verdaccio，都是这套协议的不同实现。

这套约定的核心就三类请求（以本包为例，registry = `https://npm.pkg.github.com`）：

| 动作 | HTTP 请求 | 返回/作用 |
|---|---|---|
| 查包元数据 | `GET https://npm.pkg.github.com/@talqora%2Fagent-contracts` | 返回 **packument**（JSON）：所有版本、每版的 tarball 地址与 integrity 哈希 |
| 下载某版 tarball | `GET https://npm.pkg.github.com/download/@talqora/agent-contracts/0.1.0/<sha>` | 返回 `.tgz` 二进制 |
| 发布 | `PUT https://npm.pkg.github.com/@talqora%2Fagent-contracts` | body 里带新版本元数据 + base64 编码的 tarball，服务器落库 |

（`@talqora/agent-contracts` 里的 `/` 在 URL 里被转义成 `%2F`，这是 scoped 包的约定。）

一份 **packument** 长这样（节选，真实结构）：
```json
{
  "name": "@talqora/agent-contracts",
  "dist-tags": { "latest": "0.1.0" },
  "versions": {
    "0.1.0": {
      "name": "@talqora/agent-contracts",
      "version": "0.1.0",
      "dist": {
        "tarball": "https://npm.pkg.github.com/download/@talqora/agent-contracts/0.1.0/abc123...",
        "integrity": "sha512-qUqcLrq30qrQJ...EEQbEE52rTfSg=="
      }
    }
  }
}
```
`integrity` 就是那串 `sha512-...`；客户端下载 tarball 后自己算一遍 sha512，对不上就报错——这是**防篡改/防损坏**的底层机制（SRI）。

## 2.3 一次 `publish` 完整发生了什么（逐步，带真实链路）

以 `publish-contracts.yml` 里那次为例：
1. **准备产物**：`npm run build`（tsc）产出 `dist/`；`package.json` 的 `files: ["dist"]` 决定进包的文件。
2. **打 tarball**：`npm publish` 先在本地把这些文件打成 `talqora-agent-contracts-0.1.0.tgz`，并算出 sha512 integrity。
3. **决定发到哪台服务器**：npm 读配置——因为包名是 `@talqora/...`，命中 `.npmrc` 里
   `@talqora:registry=https://npm.pkg.github.com`，于是目标 registry = GitHub Packages（**不是** npmjs.org）。
4. **鉴权**：npm 从 `.npmrc` 的 `//npm.pkg.github.com/:_authToken=<token>` 取 token，作为
   `Authorization: Bearer <token>` 头带上。CI 里这个 token 是 `NODE_AUTH_TOKEN`（= `GITHUB_TOKEN`）。
5. **发请求**：`PUT https://npm.pkg.github.com/@talqora%2Fagent-contracts`，body 含版本元数据 + base64 的 tarball。
6. **服务器端鉴权与落库**：GitHub 校验 token 是否对 `talqora` 组织有 `write:packages`；从 scope `@talqora`
   推断包归属组织 `talqora`；版本不存在则存下 tarball + 元数据，出现在 `orgs/talqora/packages`。
   （已存在同版本会 **409/403** 拒绝——npm 包**版本不可变**，这是生态铁律，保证"0.1.0 永远是同一份"。）

## 2.4 一次 `install` 完整发生了什么（.npmrc 解析 → 鉴权 → 拉取 → 校验）

以 `cd web && pnpm install` 为例，逐步：
1. **读依赖**：从 `package.json` 看到需要 `@talqora/agent-contracts@^0.1.0`。
2. **作用域路由**：包名是 `@talqora/...` → 命中 `web/.npmrc` 的
   `@talqora:registry=https://npm.pkg.github.com`，所以**只有这个作用域**去 GitHub Packages 要；
   其它包（react、antd…）仍走默认 registry（或 Docker build 传入的 npmmirror）。这就是"作用域级路由"。
3. **取鉴权**：命中 `//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}`，pnpm 把环境变量 `NODE_AUTH_TOKEN`
   展开成真实 token，之后请求带 `Authorization: Bearer <token>`。
4. **查 packument**：`GET .../@talqora%2Fagent-contracts` → 拿到版本列表；`^0.1.0` 解析出最高兼容版 `0.1.0`。
5. **下 tarball**：按 packument 里的 `dist.tarball` 地址下载 `.tgz`。
6. **校验完整性**：本地算 sha512，与 `dist.integrity` 比对；一致才解包进 `node_modules`。
7. **写 lockfile**：把解析到的确切版本 + integrity 记进 `pnpm-lock.yaml`。以后 `--frozen-lockfile`
   直接照锁文件装、不再重新解析——这就是"谁装都一样"的保证。

> 一句话对照：**publish 是 `PUT` 一个带哈希的 tarball 上去，install 是 `GET` 下来再用哈希校验**。
> registry 干的就是"按名字+版本存取 tarball，附带元数据与完整性哈希"这一件事。

## 2.5 为什么 scope 必须等于 owner（权限模型的底层）

GitHub Packages **没有**"包名随便起、单独注册"的概念。它把包的归属**直接从 scope 推断**：
`@talqora/agent-contracts` → 归属组织 `talqora`。于是：
- **发布**：token 必须对 `talqora` 组织有 `write:packages`。
- **CI 的 `GITHUB_TOKEN`**：它只代表"某仓库的这次运行"，权限边界是**该仓库所属的 owner**。所以仓库必须
  在 `talqora` 组织下，`GITHUB_TOKEN` 才对 `talqora` 的 packages 有写权——这正是我们把仓库转进组织的原因。
- 若把包名写成 `@fdahk/...` 而仓库在 `talqora` 组织，或反过来，就会 **403**：scope 与发布身份的 owner 对不上。

## 2.6 三种 token 的区别与选择

| token | 代表谁 | 生命周期 | 典型用途 | 本项目怎么用 |
|---|---|---|---|---|
| **`GITHUB_TOKEN`**（Actions 内置） | "这个仓库的这次运行" | 单次运行，跑完失效 | CI 内发布/读取本 owner 的包 | 发布 `publish-contracts.yml`（仓库在组织下即够） |
| **classic PAT** | 你本人（粗粒度） | 你设的过期时间 | 本地 `pnpm install` 拉私有包 | 步骤 A 建的 `read:packages` token |
| **fine-grained PAT** | 你本人（可精确到某组织/某权限） | 你设的 | 更安全的最小授权；给特定组织发布 | 需要时作 `PACKAGES_TOKEN`（`write:packages` on talqora） |

选择原则：**能用 `GITHUB_TOKEN` 就别建 PAT**（无泄漏面、自动轮换）；只有"本地/非 Actions 环境"或
"跨 owner 发布"才用 PAT，且优先 fine-grained、按最小权限勾。

## 2.7 可见性模型：package 的 private/public **独立于** repo

这是最反直觉的一点：**包的可见性和仓库的可见性是两套开关**。仓库 Public，不代表包 Public——
GitHub Packages 的 npm 包默认 **private**。所以本项目仓库虽公开，安装包仍要 token（步骤 A 的由来）。
把包改成 Public（步骤 D）后，读取门槛降低。二者解耦的意义：你可以"源码开源、但制品受控"，或反之。

## 2.8 与 GitHub Actions 的集成原理

- **自动令牌**：每次 workflow 运行，GitHub 临时铸一枚 `GITHUB_TOKEN` 注入运行环境，跑完即废——
  省去"把长期密钥存进仓库"的泄漏风险。
- **权限声明**：`GITHUB_TOKEN` 的能力由 workflow 顶部 `permissions:` 决定。我们写了
  `permissions: { contents: read, packages: write }`，即"能读代码、能发包"，其余一律无权（最小权限）。
- **setup-node 的作用**：`actions/setup-node` 带 `registry-url` + `scope` 时，会在运行环境写好一份
  `~/.npmrc`（作用域映射 + `_authToken=${NODE_AUTH_TOKEN}`），你只需在发布步骤把 `NODE_AUTH_TOKEN`
  设成某 token。这就是 CI 里"没手写 .npmrc 也能发/装"的原因。

## 2.9 存储与计费的底层（了解即可）

GitHub Packages 后端把每个"包@版本"的 tarball 与元数据存在 GitHub 的对象存储里，按 owner 归类、
以 registry API 对外暴露。私有包的存储与出站流量计入 GitHub 套餐额度（公开包不计）。npm 版本不可变的
铁律，使得同一 `integrity` 的 tarball 可被 CDN/客户端长期缓存——这也是为什么"删了再发同版本"通常被禁止：
会打破所有已缓存该 integrity 的消费方的一致性假设。

---

## 附：关键文件位置速查

| 文件 | 作用 |
|---|---|
| `agent-server/packages/agent-contracts/package.json` | 包名 `@talqora/agent-contracts`、version、`publishConfig.registry` |
| `agent-server/.github/workflows/publish-contracts.yml` | 发布流水线（探测版本→publish；token 优先 PACKAGES_TOKEN 回退 GITHUB_TOKEN） |
| `agent-server/.github/workflows/proto.yml` | 契约校验（lint/breaking/freshness；buf 钉 1.71.0） |
| `our-chat(web)/.npmrc` | `@talqora` 作用域路由 + `_authToken=${NODE_AUTH_TOKEN}` |
| `our-chat(web)/Dockerfile`、`docker/docker-compose.prod.yml` | 构建期以 build-arg 注入 `NODE_AUTH_TOKEN` |
| `agent-server/docs/技术方案/agent契约单一来源与类型包分发.md` | 设计与权衡（为什么这么架构） |
