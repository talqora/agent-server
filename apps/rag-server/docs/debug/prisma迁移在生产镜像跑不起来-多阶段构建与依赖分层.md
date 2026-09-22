# 为什么旧镜像跑不了 `prisma migrate deploy`——多阶段构建 + 依赖分层踩坑

> 背景：agent-server 的 node-server 容器**启动时要先把数据库迁移 apply 上去再起进程**
> （`CMD ... prisma migrate deploy && node dist/main`）。但旧的运行阶段 Dockerfile
> 用 `pnpm install --prod` 装依赖、且只 `COPY dist`，导致这条命令在生产容器里**根本无法执行**。
> 这份文档把这句话拆开讲清楚：每个名词是什么、为什么会断、怎么修、业界还有哪些做法。

---

## 0. 一句话结论

`prisma`（命令行工具 CLI）被放在 `devDependencies` 里；而生产镜像用 `pnpm install --prod`
**故意只装 `dependencies`、跳过 `devDependencies`**，于是容器里**没有 prisma 这个可执行文件**；
再加上旧 Dockerfile **只拷了编译产物 `dist/`、没拷 `prisma/` 目录**（schema 和 migration SQL 都在里面），
所以即便有 CLI 也**找不到要迁移的内容**。两个问题叠加 ⇒ 启动命令必然失败。

修法：运行阶段**直接复用构建阶段已经装好的全量 `node_modules`**（含 prisma CLI）+ **把 `prisma/` 目录也拷进去**，
顺手装上 alpine 缺的 `openssl`（prisma 查询引擎依赖它）。

---

## 1. 先扫盲：这几个角色分别是什么

### 1.1 Prisma 的两个包，职责完全不同

| 包名 | 装在哪 | 是什么 | 运行时用不用 |
|---|---|---|---|
| `@prisma/client` | `dependencies`（第 39 行） | **运行时库**：你代码里 `import { PrismaClient }` 用的就是它，负责把方法调用翻译成 SQL 发给数据库 | **要**，应用跑起来每次查询都用 |
| `prisma` | `devDependencies`（第 80 行） | **命令行工具（CLI）**：`prisma migrate`、`prisma generate`、`prisma studio` 这些命令 | 一般认为只在「开发/构建」时用，所以默认归到 dev |

这个划分是 Prisma 官方脚手架的默认习惯，逻辑是：「客户端库是产品的一部分要带上线；CLI 是工具，开发时才用」。
**这个默认假设在「启动时迁移」的部署模式下就破产了**——因为我们恰恰要在生产容器启动时调用 CLI 的 `migrate deploy`。

> 📌 `migrate deploy` vs `migrate dev`：
> - `migrate dev`：开发用，会比对 schema、**生成**新的 migration 文件、可能重置库，**绝不能上生产**。
> - `migrate deploy`：生产用，**只把已存在、还没应用的 migration 按顺序 apply 上去**，幂等、不生成、不删数据，
>   并且带库级 advisory lock（多实例同时启动也不会重复迁移）。这就是我们 CMD 里用的那条。

### 1.2 `dependencies` vs `devDependencies`

`package.json` 里两类依赖：
- `dependencies`：**生产运行必须**的（express、@prisma/client、openai…）。
- `devDependencies`：**只在开发/构建期需要**的（TypeScript 编译器、NestJS CLI、eslint、测试框架、`prisma` CLI…）。

`pnpm install --prod`（npm 是 `npm ci --omit=dev`）的语义就是：**只装 `dependencies`，跳过 `devDependencies`**。
目的是让生产镜像更小、攻击面更窄。**代价**：任何被你归到 dev 但运行时其实要用的东西，都会缺失。
这次 `prisma` CLI 就是这个代价的受害者。

### 1.3 多阶段构建（multi-stage build）

看 Dockerfile 的结构，两个 `FROM`：

```dockerfile
# ===== 阶段一 builder：负责“编译” =====
FROM node:22-alpine AS builder
...
RUN corepack enable pnpm && pnpm install --frozen-lockfile   # 装【全量】依赖(含 dev)，因为编译要 TS/NestCLI
COPY . .
RUN pnpm run build                                            # tsc 把 src/ 编成 dist/

# ===== 阶段二 runtime：负责“运行” =====
FROM node:22-alpine
...                                                           # 只把“跑起来需要的东西”从 builder 拷过来
```

**为什么要分两段？** 因为编译期需要的一大堆工具（TypeScript、NestJS CLI、各种 `@types`）
**运行时根本用不到**。多阶段构建让最终镜像**只包含运行所需**，把几百 MB 的编译工具链丢在 builder 阶段不带走，镜像更小。

**关键认知**：阶段二是一个**全新的、干净的镜像**，它和阶段一之间**唯一的桥梁就是 `COPY --from=builder`**。
你没显式 `COPY` 过来的东西，阶段二里就**不存在**。旧 Dockerfile 的 bug 正源于此——漏拷了东西。

---

## 2. 旧 Dockerfile 错在哪（两个问题叠加）

旧的运行阶段大致是这样（重建一下当时的逻辑）：

```dockerfile
FROM node:22-alpine
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable pnpm && pnpm install --prod   # ❌ 问题一：--prod 跳过 devDeps ⇒ 没有 prisma CLI
COPY --from=builder /build/dist ./dist            # ❌ 问题二：只拷 dist，没拷 prisma/
CMD ["sh","-c","./node_modules/.bin/prisma migrate deploy && node dist/main"]
```

### 问题一：`--prod` 装不出 prisma CLI

`prisma` 在 devDependencies，`--prod` 直接跳过它。
于是 `./node_modules/.bin/prisma` 这个软链**压根不存在**。
启动时 shell 执行第一条命令就报 `prisma: not found`（或 `no such file or directory`），
`&&` 短路，`node dist/main` 也不会跑 ⇒ 容器起不来、健康检查失败、`restart: unless-stopped` 无限重启。

> 还有个**连带问题**：`prisma generate`（生成 `@prisma/client` 的类型与查询引擎）是靠 `postinstall` 钩子
> （package.json 第 28 行 `"postinstall": "prisma generate"`）触发的。
> 在 `--prod` 的干净安装里，prisma CLI 没装上，`postinstall` 要么报错要么 generate 不完整，
> `@prisma/client` 也可能是没初始化的空壳。也就是说，这种装法**连应用本身的查询都未必能跑**，不只是迁移。

### 问题二：只拷 `dist/`，没拷 `prisma/`

就算你把 prisma CLI 装回来了，`migrate deploy` 还需要两样东西，**都在 `prisma/` 目录里**：

```
apps/node-server/prisma/
├── schema.prisma        # 数据模型 + datasource(连哪个库) + generator 配置
└── migrations/          # 历史每一版的 migration SQL（deploy 就是按序 apply 这些）
```

`prisma migrate deploy` 默认读 `prisma/schema.prisma` 找到 `migrations/` 目录，再去对比数据库里的
`_prisma_migrations` 表，把「文件里有、库里还没记录」的那些 SQL 依次执行。
**旧 Dockerfile 只 `COPY dist`，没把 `prisma/` 拷进运行镜像** ⇒ CLI 即使在，也会报
`Could not find schema.prisma` / 找不到任何 migration ⇒ 迁移依然跑不了。

**两个问题是 AND 关系**：CLI 缺 + schema/migrations 缺，任意一个都足以让启动迁移失败，何况两个都缺。

---

## 3. 修法（现在的 Dockerfile）

```dockerfile
# ========== 阶段二：运行 ==========
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production

# prisma 查询引擎在 alpine(musl) 上需要 openssl；wget 给容器健康检查用
RUN apk add --no-cache openssl wget

# 直接复用 builder 已装好的【全量】node_modules：里面已含 prisma CLI/引擎，
# 以及 postinstall 阶段已生成好的 @prisma/client。
# （不在 runtime 再 pnpm install --prod —— 那样 prisma 是 devDependency 会缺，无法启动迁移）
COPY --from=builder /build/node_modules ./node_modules
COPY --from=builder /build/package.json ./package.json
COPY --from=builder /build/dist ./dist
COPY --from=builder /build/prisma ./prisma          # ✅ 关键：把 schema + migrations 一起带上

RUN mkdir -p /app/storage/agent-runs
EXPOSE 3101

# 先 apply 迁移(幂等/带库级锁)，成功后再起进程
CMD ["sh","-c","./node_modules/.bin/prisma migrate deploy && node dist/main"]
```

三处关键改动：
1. **`COPY --from=builder .../node_modules`**：不在运行阶段重装，直接复用 builder 的全量依赖。
   builder 用的是 `pnpm install --frozen-lockfile`（**含 dev**），所以 prisma CLI 在里头；
   而且 `@prisma/client` 已经被 postinstall `generate` 好了，连引擎二进制都齐。
2. **`COPY --from=builder .../prisma`**：把 schema + migrations 带进运行镜像，`migrate deploy` 才有东西可 apply。
3. **`apk add openssl`**：alpine 用 musl libc，prisma 的查询引擎需要系统 `openssl` 才能起。
   这是 prisma + alpine 的经典坑——不装会在运行时报 `Unable to require libquery_engine` 之类的错。

---

## 3.5 同源的另一个坑：builder 阶段 `prisma generate` 的拷贝顺序（首次部署实测翻车）

上面修的是**运行阶段**。但首次 CI 构建在更早的**构建阶段**就挂了，错误是：

```
> prisma generate
Error: Could not find Prisma Schema that is required for this command.
  schema.prisma: file not found
  prisma/schema.prisma: file not found
```

原因同样和 Docker 分层有关。Dockerfile 为了**利用层缓存**，习惯先只拷依赖清单再装依赖：

```dockerfile
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile   # ← prisma 的 postinstall(prisma generate)在这一步就跑
COPY . .                             # ← prisma/schema.prisma 这时才被拷进来
```

关键时序：`pnpm install` 会触发 package.json 里的 `"postinstall": "prisma generate"`，
而 `prisma generate` 要读 `prisma/schema.prisma`。可此刻 `COPY . .` **还没执行**——构建上下文里只有
package.json + lockfile，schema 根本不在 ⇒ generate 找不到 schema ⇒ install 失败 ⇒ 整个构建失败。

> 为什么本地 `pnpm install` 不报这个错？因为本地是在一个 schema 已经躺在 `prisma/` 里的完整工作区跑的，
> generate 当然找得到。Docker 「先拷清单、后拷源码」的切分是为缓存人为做的，恰好把 schema 切到了 install 之后。

**修法**：在 `install` 之前先把 `prisma/` 拷进去：

```dockerfile
COPY package.json pnpm-lock.yaml ./
COPY prisma ./prisma                 # ← 关键:让 postinstall 的 generate 找得到 schema
RUN pnpm install --frozen-lockfile
COPY . .                             # node_modules 在 .dockerignore,不会覆盖已生成的 client
```

既保留「依赖层缓存」（schema 变动远少于源码），又让 postinstall 正常生成 client。

> 另一种思路是 `pnpm install --ignore-scripts` 跳过所有 postinstall、之后再显式 `prisma generate`。
> 不推荐：会连带跳过 bcrypt 等原生模块的构建脚本，引新坑。单独拷 `prisma/` 是更外科的修法。

> 📌 和第 2 节的运行阶段联动：builder 这里 generate 出来的 client 在 `node_modules` 里，
> 运行阶段 `COPY --from=builder .../node_modules` 直接搬走——所以**只要 builder 这步成功，运行阶段就有现成 client**，
> 不必在 runtime 再 generate 一次。两个坑其实是同一根线（prisma 产物 + Docker 分层）的两端。

---

## 4. 取舍：为什么直接拷全量 node_modules，而不是 runtime 再 `--prod`

这是这次修复里**唯一有争议、值得展开**的设计点。两条路：

### 路线 A（采用）：runtime 复用 builder 的全量 node_modules
- ✅ 简单、可靠：依赖只在 builder 装一次，runtime 不再联网、不再触发 postinstall，构建更快更稳。
- ✅ prisma CLI、引擎、已生成的 client 一并带上，启动迁移天然可用。
- ❌ 镜像偏大：把 eslint/测试框架/TS 编译器等 devDeps 也带进了运行镜像（几十～上百 MB 冗余）。
- ❌ 攻击面略大：生产镜像里多了一堆运行时用不到的包。

### 路线 B（没采用）：把 `prisma` 挪到 `dependencies`，runtime 仍 `--prod`
- ✅ 镜像最干净：只装真正运行要用的包。
- ❌ 需要改 package.json 的依赖归类（动到应用元数据），而且光挪 `prisma` 还不够——
  runtime 重新 `--prod` 安装会**再次触发 postinstall `prisma generate`**，要保证引擎能正确下载/生成，
  还得处理 pnpm 在 `--prod` 下对 `onlyBuiltDependencies`、网络、缓存的一致性。链路更长、更容易出新坑。
- ❌ runtime 多一次完整 `install`，构建更慢，且把「能否联网装包」变成部署成败的依赖。

**为什么选 A**：这个项目当前阶段，**部署可靠性 > 镜像体积优化**。
镜像大几十 MB 在单机自托管场景几乎无感；而 B 的「runtime 再装一次 + 再 generate 一次」引入的失败点
（网络、引擎下载、postinstall）才是真正会让你半夜重启容器的东西。
等真要抠镜像体积，更专业的做法见下一节，而不是简单把 prisma 挪到 deps。

---

## 5. 业界还有哪些做法（进阶，做对比用）

> 「启动时自动迁移」本身在业界是**有争议**的，下面把谱系列清楚，知道我们在光谱的哪个位置。

1. **本项目这种「应用容器启动时 `migrate deploy`」**
   - 优点：零额外编排，`up -d` 就自愈，单机/小团队最省心。
   - 缺点：多副本同时启动会争锁（prisma 有库级锁兜底，能串行化，但 deploy 期间该实例不可用）；
     迁移失败 = 容器起不来。适合**单实例或小规模**，正是我们的场景。

2. **独立的「迁移 Job / init 容器」先跑，应用容器再起**
   - K8s 里常见：一个 `Job` 或 `initContainer` 专门 `migrate deploy`，成功后才滚动更新应用 Pod。
   - 优点：迁移与启动解耦，应用镜像可以彻底 `--prod` 不带 CLI；迁移失败不会让应用反复重启。
   - 缺点：要多一套编排。Compose 单机下没必要上这套。

3. **把 prisma 引擎二进制单独 COPY，而非整包 node_modules**
   - 极致瘦身：runtime `--prod` + 只从 builder 拷 `node_modules/prisma`、`node_modules/@prisma`、`.bin/prisma`、`prisma/`。
   - 优点：镜像小、又能跑迁移。缺点：要精确知道 prisma 把引擎放哪、版本升级时路径会变，维护成本高。
   - 这是「真的在乎镜像体积」时路线 A 的进化版。

4. **CI 阶段就把迁移 apply 到目标库，镜像里完全不带迁移能力**
   - 在 GitHub Actions 里连上数据库跑 `migrate deploy`，应用镜像纯运行时。
   - 优点：镜像最干净、迁移在受控环境执行、失败早暴露。
   - 缺点：CI runner 要能直连生产库（网络/安全成本），我们的库在内网 compose 里，CI 够不着，不适用。

**我们处在第 1 档**，因为是单机自托管、Compose、单实例——这一档对「省心」的权重最高。

---

## 6. 顺带说一个相关设计：worker 用同一镜像但**不迁移**

compose 里 `node-worker` 复用同一个镜像，但**覆盖了 CMD**：

```yaml
node-worker:
  image: ${AGENT_IMAGE}
  command: ['node', 'dist/main.worker']   # 覆盖掉 Dockerfile 里“先迁移再起”的默认 CMD
  depends_on:
    node-server: { condition: service_healthy }   # 等 server 健康(迁移已 apply)再起
```

- **为什么 worker 不迁移**：迁移只能由**一个**入口负责，否则 server 和 worker 启动时抢着 apply 同一批 migration，
  虽然有库级锁不会损坏数据，但语义混乱、日志难看。约定**只有 node-server 迁移**，worker 纯消费。
- **怎么保证 worker 不打到「还没迁移」的库**：靠 `depends_on: node-server 健康`。
  server 的健康检查通过，意味着它已经把 `migrate deploy` 跑完、HTTP 起来了，此时库 schema 是最新的，worker 再起就安全。

这也解释了为什么「迁移」这件事必须**绑在某一个明确入口的 CMD 上**，而不是塞进镜像的某个通用启动脚本里——
同一镜像被两种角色复用时，迁移归属要清清楚楚。

---

## 7. 自检清单（以后改 Dockerfile 别再踩）

- [ ] 运行时要用的命令行工具（prisma、任何 `*-cli`）是否在 `devDependencies`？若 runtime 会 `--prod`，它就会缺。
- [ ] `migrate deploy` 依赖的 `prisma/`（schema + migrations）是否 `COPY` 进了运行阶段？
- [ ] alpine 基镜是否 `apk add openssl`？prisma 查询引擎在 musl 上需要它。
- [ ] `@prisma/client` 是否已 `generate`（postinstall 跑过、或从 builder 拷了生成产物）？
- [ ] builder 阶段：`prisma/` 是否在 `pnpm install` **之前**拷入？否则 postinstall 的 `prisma generate` 找不到 schema，install 直接失败。
- [ ] 多入口（server/worker）复用同一镜像时，**迁移只挂在一个入口的 CMD 上**，另一个 `depends_on` 它健康。
- [ ] 多阶段构建里，凡是运行需要、又没显式 `COPY --from=builder` 的，运行阶段一律不存在——逐个对照。
