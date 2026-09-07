# @talqora/agent-contracts

agent-server 对外暴露的**客户端契约类型**(TypeScript)。

## 这是什么 / 解决什么问题

agent-server 是一个可被多个项目复用的 RAG + Agent 微服务。消费方(如 our-chat 的
web 端)需要一份与服务端**始终一致**的请求/响应类型,否则容易出现"服务端改了字段、
前端还按老结构解析"的契约漂移。

为避免各消费方各自手抄类型,本包把契约的**权威来源**——
`agent-server/proto/ourchat/agent/v1/agent.proto`——经 `buf generate`(ts-proto,
`onlyTypes`)生成为 TS 类型,发布到 GitHub Packages。消费方 `npm/pnpm install` 即可。

> 权威是 proto,不是本包。多语言消费方(Go/Python/Swift 等)从**同一份 proto**各自
> 生成,不依赖本 TS 包。本包只是 proto 面向 TS 消费方的产物之一。

## 用法

```ts
import type { AgentRun, Citation, AgentTaskSession } from '@talqora/agent-contracts';
```

## 维护

- 不要手改 `src/gen/**`:由 `buf generate` 覆写(仓库根 `buf.gen.yaml` 第二个输出)。
- 改契约 = 改 `proto/ourchat/agent/v1/agent.proto` → `buf generate` → bump 本包
  `version`(破坏性变更走 major)→ 合并到 main 触发 `publish-contracts.yml` 发布。
- `proto.yml` CI 校验 lint / breaking-change / 生成物新鲜度。
