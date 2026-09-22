# 后端标准架构方案综述

## 写在前面

所谓“大厂标准”，通常不是指所有项目都必须长成同一种目录结构，而是指：

- 能根据业务复杂度选择合适的架构形态
- 能把业务逻辑、协议层、存储层、外部依赖清晰隔离
- 能支撑测试、扩展、稳定性治理和团队协作
- 能在不过度设计的前提下，为未来演进保留空间

---

## 一、常见后端架构流派总览

目前工程里最常见、也最容易在大厂里看到的后端架构思路，基本可以归为以下几类：

1. 经典三层架构：`Controller -> Service -> DAO/Mapper`
2. 模块化分层架构：按业务模块拆分，每个模块内部再做分层
3. DDD-lite 架构：`interfaces -> application -> domain -> infrastructure`
4. Port-Adapter / Hexagonal 架构：在 DDD-lite 基础上进一步引入 `port` 与 `adapter`
5. 事件驱动架构：在业务主链路之外，通过 MQ、事件总线做异步解耦
6. 微服务架构：多个独立服务通过 RPC、HTTP、MQ 协作

它们不是互斥关系。真实项目里经常是组合使用：

- 一个系统总体是“模块化单体”
- 模块内部采用 `application + domain + infrastructure`
- 一部分能力通过 MQ 变成事件驱动
- 到一定规模后，再拆成多个微服务

---

## 二、不同业务场景下的推荐标准架构

## 1. 简单 CRUD / 后台管理系统

### 推荐方案

经典三层架构或模块化三层架构。

### 典型结构

```text
controller
service
mapper / repository
entity / dto
```

### 核心思路

这类系统的核心目标通常不是复杂业务建模，而是：

- 快速交付
- 清晰维护
- 数据库增删改查稳定可靠

因此没有必要一开始就引入很重的领域分层。只要做到以下几点就足够标准：

- 控制器不写业务
- Service 承担业务编排
- Mapper/Repository 只负责持久化
- DTO、Entity、VO 边界清楚

### 优点

- 上手快
- 团队普遍熟悉
- 开发成本低
- 对简单业务足够有效

### 缺点

- 当业务逻辑变复杂时，Service 很容易膨胀
- 容易出现“万能 Service”
- 外部依赖、规则判断、流程编排容易混在一起

### 适用场景

- 管理后台
- CMS
- 配置中心
- 权限系统初版
- 普通运营平台

---

## 2. 中等复杂度业务单体

### 推荐方案

模块化分层架构，或者轻量 DDD-lite。

### 典型结构

```text
modules/
  order/
    controller
    service
    mapper
    dto
  user/
    controller
    service
    mapper
    dto
shared/
config/
common/
```

或者：

```text
modules/
  order/
    interfaces
    application
    domain
    infrastructure
```

### 核心思路

这类系统已经不是单纯 CRUD，往往会开始出现：

- 多步骤业务流程
- 多外部系统调用
- 权限、审计、状态流转
- 一定程度的领域规则

这时最重要的不是立刻做重型 DDD，而是先把“按业务模块隔离”建立起来，防止代码全堆在一起。

### 优点

- 比经典三层更抗膨胀
- 能让不同业务模块边界更清楚
- 适合逐步演进

### 缺点

- 如果团队规范差，仍然会演变成“模块内大 Service”
- domain 容易沦为空壳

### 适用场景

- 电商订单系统初中期
- 中后台交易系统
- 内容审核系统
- 业务流程型平台

---

## 3. 外部依赖多、流程编排重的业务系统

### 推荐方案

`application service + domain + infrastructure`，必要时加入 `port + adapter`。

### 典型结构

```text
interfaces/
application/
domain/
infrastructure/
```

### 核心思路

这类系统的痛点通常不是“一个 SQL 怎么写”，而是：

- 要同时调用数据库、缓存、MQ、第三方 API、文件系统、搜索引擎
- 一个业务用例会跨越多个步骤
- 需要把业务规则与技术实现解耦
- 后续可能替换某个基础设施实现

所以要做的不是把一切都塞进 `Service`，而是分层：

- `interfaces`：接收 HTTP、RPC、消息等输入输出
- `application`：负责用例编排和事务边界
- `domain`：描述领域对象、规则、领域服务、领域接口
- `infrastructure`：数据库、缓存、MQ、外部 API、文件系统等技术实现

### 优点

- 业务编排边界清晰
- 对外部依赖替换更友好
- 测试更容易分层做
- 更适合长期演进

### 缺点

- 比三层架构复杂
- 团队如果不理解，容易写成“多目录版三层”
- 过早引入可能造成设计负担

### 适用场景

- 风控系统
- 结算系统
- 资源编排系统
- AI Agent 编排系统
- 数据同步与处理平台

---

## 4. 核心领域复杂、长期演进的大型核心系统

### 推荐方案

DDD-lite 到 DDD 中等强度实现，结合 `port + adapter`。

### 典型结构

```text
interfaces/
application/
domain/
  model/
  service/
  gateway/
infrastructure/
  persistence/
  rpc/
  mq/
  cache/
```

### 核心思路

这类系统的重点是“领域复杂性”，比如：

- 订单生命周期复杂
- 营销规则复杂
- 风控规则复杂
- 库存扣减、一致性、补偿逻辑复杂

真正需要被隔离的是“业务知识”，不是“目录树”。

所以 domain 层通常会承载：

- 聚合根
- 值对象
- 领域服务
- 领域规则
- 领域网关接口

而 infrastructure 去实现这些接口，例如：

- `OrderRepository`
- `RiskRuleGateway`
- `CouponGateway`
- `InventoryGateway`

### 优点

- 对复杂业务最友好
- 业务语言更清晰
- 更适合多人协作和长期演进

### 缺点

- 学习门槛高
- 如果业务其实不复杂，会显得很重
- 团队设计能力不够时，容易形式主义

### 适用场景

- 核心交易域
- 结算域
- 库存域
- 营销中台
- 风控中台

---

## 5. 高并发异步处理场景

### 推荐方案

分层架构 + 事件驱动架构，而不是只看目录分层。

### 核心思路

这类场景的关键问题通常是：

- 吞吐
- 削峰
- 解耦
- 最终一致性
- 重试与幂等

因此重点不在于 controller/service 怎么切，而在于系统是否具备：

- 事件发布与消费
- 幂等控制
- 重试与死信处理
- 补偿逻辑
- 延迟任务

换句话说，这里“标准架构”往往体现为：

- 主链路同步最小化
- 次链路异步化
- 业务状态机清晰
- 事件模型稳定

### 适用场景

- 秒杀
- 异步订单处理
- 通知中心
- 数据同步管道
- 报表计算系统

---

## 6. 大规模组织协作场景

### 推荐方案

先模块化单体，再谨慎演进微服务，而不是一开始就盲目全拆。

### 核心思路

很多人误以为“大厂标准架构 = 微服务”，这是不准确的。

真实情况通常是：

- 单体阶段先把模块边界理顺
- 识别高变更、高流量、独立生命周期模块
- 再按团队边界、数据边界、部署边界逐步拆分

微服务适合解决的是：

- 团队协作边界
- 独立扩容
- 独立部署
- 技术异构

但微服务会带来更高的复杂度：

- 分布式事务
- 服务治理
- 链路追踪
- 配置中心
- 网关
- 降级熔断
- 灰度发布

所以它不是“默认更高级”，而是“更高代价的组织化方案”。

---

## 三、架构思路与原理

## 1. 为什么要分层

分层的本质不是为了目录好看，而是为了隔离变化。

后端系统里最常变化的东西通常包括：

- 接口协议会变
- 业务规则会变
- 数据库表结构会变
- 第三方 API 会变
- 消息系统、缓存、搜索系统会变

如果所有代码都写在一个大 Service 里，那么任何变化都会引发连锁修改。

因此标准架构的本质原则是：

- 把变化频率不同的东西隔离开
- 把业务逻辑和技术细节隔离开
- 把输入输出协议和内部模型隔离开

---

## 2. application 层的原理

`application service` 不是传统意义上的“业务实现大杂烩”，它更准确的职责是：

- 表达一个业务用例
- 负责编排步骤
- 处理事务边界
- 调用领域对象和网关
- 组织输入输出

它回答的问题是：

- “这个用例要怎么走”

而不是：

- “底层数据库怎么查”
- “第三方 API 怎么发请求”
- “某个复杂规则细节怎么判定”

---

## 3. domain 层的原理

domain 层的核心不是“放实体类”，而是承载业务语义。

它回答的问题是：

- 什么是订单
- 什么是任务运行状态
- 什么情况下允许状态流转
- 某条规则是否成立
- 某个领域动作是否允许发生

在简单项目里，domain 可能比较轻。
在复杂项目里，domain 是整个系统最核心、最稳定的一层。

---

## 4. gateway / port 的原理

`gateway` 或 `port` 的本质，是对外部依赖做抽象。

比如 domain 或 application 不应该关心：

- 你现在用的是 MyBatis 还是 JPA
- 你现在调的是 Ollama 还是 OpenAI
- 你现在把文件写到本地还是对象存储

它只应该关心：

- 我需要“查询任务”
- 我需要“保存运行事件”
- 我需要“调用模型完成摘要”
- 我需要“输出最终报告”

所以会出现类似接口：

```java
public interface LlmGateway {
    String completeText(...);
}
```

然后由 infrastructure 去实现：

- `OllamaLlmAdapter`
- `OpenAiLlmAdapter`

这就是 port-adapter 的核心思想。

---

## 5. infrastructure adapter 的原理

infrastructure 的职责不是承载业务规则，而是承载技术实现。

典型包括：

- MyBatis Mapper
- Redis 客户端
- MQ Producer/Consumer
- HTTP Client
- 第三方 SDK 封装
- 文件存储实现

如果 application 直接依赖这些具体实现，业务层会很快被技术细节污染。

所以更成熟的做法是：

- application 依赖抽象
- infrastructure 实现抽象

这会让系统更易测、更好换实现、更利于演进。

---

## 四、几种主流架构的横向比较

| 方案 | 复杂度 | 上手成本 | 可维护性 | 扩展性 | 测试友好度 | 面试含金量 | 适用阶段 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 经典三层 | 低 | 低 | 中 | 中 | 中 | 中 | 简单项目 |
| 模块化三层 | 中 | 低 | 中高 | 中高 | 中 | 中高 | 中等复杂系统 |
| DDD-lite | 中高 | 中 | 高 | 高 | 高 | 高 | 编排型、规则型系统 |
| Port-Adapter/Hexagonal-lite | 高 | 中高 | 高 | 很高 | 很高 | 很高 | 外部依赖多、需要长期演进 |
| 重型 DDD | 很高 | 高 | 很高 | 很高 | 高 | 高 | 超复杂核心域 |
| 微服务 | 很高 | 高 | 取决于治理水平 | 很高 | 低到中 | 高 | 大规模团队协作 |

---

## 五、这些架构之间的关系

很多人会把这些名字理解成“非此即彼”，其实不是。

更准确的理解是：

- 经典三层，是最基础的工程分层
- 模块化三层，是在三层上增加业务边界
- DDD-lite，是在模块化基础上进一步强调业务语义和层次职责
- Port-Adapter，是在 DDD-lite 上进一步强调“依赖抽象”
- 微服务，是系统部署与组织协作层面的拆分，不是单纯代码目录问题

所以一个成熟系统完全可能同时具备：

- 模块化单体
- DDD-lite 分层
- 某些模块使用 port-adapter
- 某些链路使用事件驱动

---

## 六、与 Node 项目架构的比较

## 1. Node 项目架构特点

原 `agent-server` 的 Node/Nest 版本，本质上更接近：

- Nest 模块化结构
- `controller + service + provider`
- 运行态以内存状态管理为主
- 外部依赖直接在 service/provider 内调用

从业务上看，它已经具备了一些不错的模块意识：

- `resource-organizer-agent` 作为独立模块
- `controller.ts` 负责接口
- `service.ts` 负责主流程
- `providers/ollama.provider.ts` 封装模型调用
- `services/resource-collection.service.ts` 封装资源采集
- `services/report.service.ts` 封装报告输出
- `services/run-store.service.ts` 用于 run 状态和 SSE

这说明原 Node 项目并不是“乱写”，而是一个比较典型的 Nest 模块化项目。

---

## 2. 原 Node 架构的优点

### 优点一：开发快

Nest 天生适合快速把模块、控制器、服务搭起来，业务上线速度快。

### 优点二：结构天然比 Express 裸写更好

至少已经有：

- 模块边界
- 控制器与服务分离
- Provider 抽象

### 优点三：对当前业务验证非常高效

对于早期验证资源采集、LLM 调用、SSE 回传、报告生成，这种结构非常合适。

---

## 3. 原 Node 架构的局限

### 局限一：核心流程编排和基础设施容易耦合

虽然 Node 版本拆了多个 service/provider，但总体上仍然更接近“流程大 service + 若干工具 service”。

### 局限二：状态管理偏运行时、偏内存

原项目大量依赖：

- `Map`
- `RxJS Subject`
- 内存 run store

这对单机演示很方便，但对大厂标准来说还不够，因为缺少：

- 持久化状态
- 故障恢复能力
- 水平扩展友好性
- 更明确的事件存储和审计链路

### 局限三：领域边界不够明确

Node 版本更强调“把功能做出来”，但没有把：

- 任务运行
- 资源采集
- 模型交互
- 报告输出
- 事件流转

抽象成更清晰的业务用例和依赖边界。

### 局限四：架构表达力偏弱

如果你拿它去面大厂后端岗位，面试官会更容易把它理解成：

- 一个完成度不错的 Node 工程项目

而不是：

- 一个体现复杂业务编排、系统设计、依赖治理能力的 Java 后端项目

---

## 4. 当前 Java 项目与原 Node 架构的差异

当前 Java 项目相较原 Node 项目，已经发生了几类关键变化：

### 变化一：从“内存运行态”转向“持久化运行态”

现在引入了：

- MyBatis
- Flyway
- 运行记录表
- 运行事件表

这意味着任务状态、事件历史、结果快照都可以持久化，而不是仅存在内存里。

### 变化二：从 Nest 模块化转向更明确的企业级分层

现在已经开始使用：

- `interfaces`
- `application`
- `domain`
- `infrastructure`

这种分层比原先的 `controller/service/provider` 更容易表达：

- 哪些是协议层
- 哪些是业务用例编排
- 哪些是领域对象
- 哪些是技术实现

### 变化三：更适合后续接入企业级能力

例如未来接入：

- Redis
- RabbitMQ
- MySQL 正式环境
- 监控告警
- 对象存储
- 多模型切换

在 Java 当前结构下，比原 Node 结构更容易稳态演进。

---

## 5. 原 Node 架构和当前 Java 架构谁更好

不能简单说谁“绝对更好”，而应该看目标。

### 如果目标是快速验证产品

原 Node/Nest 架构很好，开发效率高，业务验证快。

### 如果目标是做大厂 Java 后端作品集

当前 Java 架构更合适，因为它更容易承载：

- 持久化
- 分层治理
- 可替换基础设施
- 后续异步化
- 可观测性
- 架构表达力

### 如果目标是长期演进为企业级服务

Java 版本更有优势，但前提是不要过度设计，要循序渐进。

---

## 七、对当前 agent-server 的架构建议

结合当前项目业务特点：

- 不是纯 CRUD
- 有明显流程编排
- 有数据库、SSE、文件、HTTP、LLM 等多类外部依赖
- 后续大概率会继续接 Redis、RabbitMQ、监控能力

我认为最合适的架构形态不是“传统三层”，也不是“重型 DDD”，而是：

## 推荐：DDD-lite + Port-Adapter-lite

也就是：

- `interfaces` 负责 HTTP/SSE/鉴权输入输出
- `application` 负责用例编排和任务生命周期
- `domain` 放核心领域模型、状态、port 接口
- `infrastructure` 放数据库、Ollama、文件、消息、缓存等 adapter

这套方案的优点是：

- 比三层更能体现架构能力
- 比重型 DDD 更克制
- 对当前项目复杂度刚好
- 很适合作为大厂 Java 后端作品集

---

## 八、当前项目后续推荐演进路径

如果继续按更成熟的大厂风格优化，建议按下面顺序推进：

1. 先完成当前 `interfaces / application / domain / infrastructure` 的稳定收敛
2. 再把 `Ollama`、`报告输出`、`资源采集` 抽成 `domain gateway/port`
3. 再把 `MyBatis mapper` 进一步包装为 repository/gateway 适配层
4. 再补 Redis、RabbitMQ、监控指标、结构化日志
5. 最后根据业务边界评估是否需要拆服务，而不是现在就上微服务

---

## 九、agent-server 最终项目架构方案

## 1. 最终架构结论

对于当前 `agent-server`，最终推荐方案不是“纯 Java 单体”，也不是“恢复旧 Node 主项目”，而是：

## 推荐落地方案：`Java Core + Node AI Gateway`

职责边界如下：

- `Java Core`：作为唯一对外主服务，负责认证授权、任务创建、状态持久化、事件审计、SSE 历史回放、文件输出、配置治理、稳定性治理。
- `Node AI Gateway`：作为内部 AI 服务，负责模型适配、Prompt 编排、规划、摘要、记忆聚合、最终回答生成，以及后续工具调用和多模型路由。

这个方案相比“纯 Java”更优的原因不是语言偏好，而是它更符合当前系统内部两类能力的变化规律：

- 平台治理能力变化慢，但对稳定性要求高，适合放在 Java。
- AI 编排与模型接入变化快，试错频繁，适合放在 Node。

---

## 2. 为什么不是恢复旧 Node 项目

原 Node 项目中，真正值得恢复的是：

- Ollama / 模型接入能力
- Prompt 编排能力
- AI 任务处理流程
- 后续工具调用与工作流编排能力

而不应该恢复的是：

- 原先作为主系统的控制器层
- 用户、权限、运行状态主链路
- 以单机内存为核心的任务状态管理

因此这次不是“回滚到旧 Node 后端”，而是：

- 保留 Java 主系统
- 选择性恢复并重组 Node 中的 AI 核心能力
- 让 Node 成为内部 AI Gateway，而不是重新成为系统主入口

---

## 3. 最终仓库结构

目标目录结构如下：

```text
agent-server/
  apps/
    java-server/
      pom.xml
      mvnw
      mvnw.cmd
      .mvn/
      src/
    node-server/
      package.json
      tsconfig.json
      src/
  docs/
    backend/
      architecture.md
  infra/
    docker/
    nginx/
  .gitignore
  README.md
```

说明：

- `apps/java-server` 是长期主系统目录。
- `apps/node-server` 是内部 AI 能力目录。
- `docs` 负责架构、设计、技术说明。
- `infra` 负责部署与运行配置。

### 当前实施策略

为了降低一次性目录大迁移的风险，实施阶段会分步推进：

1. 先在当前仓库内补齐 `node-server`
2. 让 Java 已经具备“可外接 Node”的抽象
3. 确认混合架构可运行
4. 再把 Java 根项目平滑迁入 `apps/java-server`

也就是说，仓库最终会整理成上述结构，但实施不是一次性粗暴搬家，而是分阶段完成。

---

## 十、服务边界设计

## 1. Java Core 职责

Java Core 负责所有需要高一致性、可审计、可治理的核心平台能力：

- 用户体系与认证授权
- API 对外接入
- Run 创建、状态流转、事件记录
- 持久化存储与 Flyway 迁移
- SSE 历史回放与实时分发
- 输出文件管理
- 后续 Redis 缓存、RabbitMQ 异步、审计日志、指标、告警

### Java Core 绝不下沉给 Node 的能力

- 用户身份认证
- 权限边界控制
- 任务主状态机
- Run ID 生成
- 审计事件落库
- 对外 API 契约
- 核心安全策略

这些能力必须掌握在 Java 主系统里，否则系统边界会倒置。

---

## 2. Node AI Gateway 职责

Node AI Gateway 负责所有高变化、高 IO、高实验性的 AI 能力：

- 模型选择与路由
- Ollama / OpenAI / 其他模型接入
- Prompt 模板管理
- 规划、摘要、聚合、最终回答生成
- 后续工具调用、Agent workflow、流式模型能力
- 针对不同模型差异做适配

### Node AI Gateway 不负责的内容

- 用户登录
- 主 API 对外暴露
- Run 状态最终裁定
- 审计落库
- 任务元数据管理

Node 只服务于 Java，不直接承担平台主系统角色。

---

## 十一、服务交互协议

## 1. 通信方式

第一阶段采用：

- `Java Core -> HTTP -> Node AI Gateway`

原因：

- 简单直接
- 易调试
- 足够支撑当前系统规模
- 便于后续替换为 MQ 或 gRPC

### 后续演进

当 AI 任务吞吐明显上升时，再考虑：

- Java 接 MQ
- Node 作为 Worker 消费

但这不是当前第一阶段必须项。

---

## 2. 内部接口契约

Java 到 Node 的内部接口统一放在 `/internal/agent/*`：

- `POST /internal/agent/plan`
- `POST /internal/agent/summarize`
- `POST /internal/agent/memory`
- `POST /internal/agent/final-answer`

### `POST /internal/agent/plan`

输入：

```json
{
  "task": "整理 React 项目资料",
  "directories": ["D:/proj/docs"],
  "urls": ["https://example.com"],
  "model": "qwen2.5:7b"
}
```

输出：

```json
[
  {
    "id": "scan_local_directory",
    "title": "扫描指定目录",
    "detail": "遍历用户指定目录并收集资源",
    "status": "pending"
  }
]
```

### `POST /internal/agent/summarize`

输入：任务描述、单个资源、模型信息  
输出：标准 `ResourceSummary`

### `POST /internal/agent/memory`

输入：任务描述、资源摘要列表、模型信息  
输出：标准 `AgentMemory`

### `POST /internal/agent/final-answer`

输入：任务描述、资源摘要、记忆、模型信息  
输出：

```json
{
  "content": "## 整理结果\n..."
}
```

---

## 3. 内部安全设计

Node AI Gateway 不应该裸奔。

第一阶段至少要具备：

- 内部网络访问限制
- `X-Internal-Token` 头校验
- 非法请求拒绝
- 超时控制

后续可增强：

- mTLS
- 网关白名单
- 签名校验
- 调用方服务身份认证

---

## 十二、数据与状态流设计

## 1. Run 生命周期

Run 生命周期由 Java 主导：

1. 客户端请求 Java 创建任务
2. Java 生成 `runId`
3. Java 持久化 `agent_runs`
4. Java 写入 `run_queued` 事件
5. Java 异步执行 Agent 流程
6. Java 在需要 AI 决策时调用 Node AI Gateway
7. Java 将阶段结果持续写入 `agent_run_events`
8. Java 生成最终结果并更新 `completed/failed`

结论：

- Node 不拥有 run 生命周期
- Node 只提供 AI 计算能力
- Java 永远是状态源头

---

## 2. 为什么资源采集和落盘暂时保留在 Java

虽然 Node 更适合做部分 IO，但当前阶段我建议：

- 资源采集先留在 Java
- 输出文件先留在 Java

原因：

- 这些动作和 run 生命周期强绑定
- 它们天然属于主系统审计链路的一部分
- 如果现在就把采集和落盘下沉给 Node，会扩大 Java 与 Node 的共享协议面
- 当前最应该优先外置的是 AI 编排，不是所有 IO

也就是说，方案二不是“Node 做所有 IO”，而是“Node 做最适合被解耦出去的 AI IO”。

---

## 十三、技术选型细节

## 1. Java Core 技术栈

- `Java 17`
- `Spring Boot`
- `Spring Web`
- `Spring Security`
- `MyBatis`
- `Flyway`
- `MySQL`
- `H2`（测试/本地）
- `Redis`
- `RabbitMQ`
- `Micrometer`
- `OpenAPI`

### Java Core 设计原则

- 统一对外 API 契约
- 主状态机只在 Java
- 对 AI 只依赖 port 接口
- 保证任何 Node 故障不会破坏任务主状态管理

---

## 2. Node AI Gateway 技术栈

推荐：

- `Node.js + TypeScript`
- `NestJS`
- `axios` 或原生 `fetch`
- 可按需接入 `zod` / `class-validator`

### 为什么这里继续用 Nest

- 原项目就是 Nest，迁移和复用成本低
- 模块化结构对内部服务足够清晰
- 守卫、模块、控制器、服务组织能力成熟
- 对后续扩展多模型适配、工具调用也友好

这里使用 Nest 的目标不是恢复旧后端主系统，而是低成本复用原来的 Node 工程能力。

---

## 十四、配置设计

Java 侧配置：

- `app.ai.mode=local-ollama | node-gateway`
- `app.ai.remote-base-url`
- `app.ai.remote-timeout-ms`
- `app.ai.remote-api-key`

Node 侧配置：

- `PORT=3101`
- `INTERNAL_TOKEN=...`
- `OLLAMA_BASE_URL=...`
- `OLLAMA_MODEL=...`
- `OLLAMA_HTTP_TIMEOUT_MS=...`

### 配置原则

- 所有敏感信息走环境变量
- Java 和 Node 的内部鉴权 token 不提交到 git
- Java 通过 profile 决定是否接本地 Ollama 或 Node Gateway

---

## 十五、失败处理与稳定性策略

## 1. Node 不可用时

Java 应按以下原则处理：

- 调用超时必须可控
- Run 状态必须明确标记失败
- 失败原因写入事件流
- 不允许出现“状态未知”

## 2. 模型返回非法 JSON 时

Java 仍然要保留兜底逻辑：

- 规划失败 -> 回退到本地 fallback plan
- 摘要失败 -> 回退到简化摘要
- 聚合失败 -> 回退到默认聚类
- 最终回答失败 -> 回退到本地 Markdown 拼装

Node 不应被视为绝对可靠服务，Java 要保留平台级容错。

---

## 十六、可观测性设计

第一阶段至少要补这些可观测字段：

- `runId`
- `requestId`
- `userId`
- `aiMode`
- `model`
- `eventType`
- `elapsedMs`

Node AI Gateway 也要统一打：

- 内部请求路径
- 模型名称
- 耗时
- 调用结果状态
- 错误类型

这样混合架构下排障才有依据。

---

## 十七、测试策略

## 1. Java Core

- 单测：状态流转、事件写入、fallback 逻辑
- 集成测试：H2 + Flyway + Controller
- 契约测试：验证对 Node AI Gateway 的响应解析

## 2. Node AI Gateway

- 单测：Prompt 生成、JSON 提取、鉴权校验
- 集成测试：内部接口响应结构
- Mock 测试：模拟 Ollama 返回异常、空结果、非法 JSON

## 3. 联调测试

- Java 调 Node plan/summarize/memory/final-answer
- Java 事件流与 Node 返回值正确对接
- Node 不可用时 Java 的失败兜底

---

## 十八、实施阶段规划

## 阶段 1：已完成

- Java 主系统完成分层
- AI 能力已抽成 `AgentAiGateway`
- 已支持 `local-ollama` 与 `node-gateway` 两种模式切换

## 阶段 2：本次开始实施

- 新增 `Node AI Gateway` 子服务
- 恢复并复用旧 Node 中的 AI 相关思路
- 对齐 Java 当前定义的 4 个内部接口

## 阶段 3：后续实施

- 把 Java 根项目迁移至 `apps/java-server`
- 让仓库变成标准多应用结构
- 补 `infra/docker` 和统一启动脚本

## 阶段 4：增强治理

- 结构化日志
- 指标埋点
- Redis 缓存
- RabbitMQ 异步任务
- 内部调用鉴权增强

---

## 十九、自审清单

在正式实施前，对方案做如下审计：

### 审计项 1：职责边界是否清晰

结论：清晰。  
Java 掌控主状态、审计与安全；Node 负责 AI 编排与模型接入。

### 审计项 2：是否会造成过度分布式

结论：不会。  
当前只有一个 Java 主服务和一个内部 Node 服务，仍属于轻量双服务架构，不是复杂微服务网。

### 审计项 3：是否会让 Java 主服务失去价值

结论：不会。  
Java 仍承担后端工程师最核心的平台能力，而且这些能力恰恰是大厂后端更看重的部分。

### 审计项 4：是否只是把问题转移给 Node

结论：不会。  
Node 只接 AI 变化快的部分，不接平台主状态与主治理逻辑。

### 审计项 5：是否支持未来继续演进

结论：支持。  
可以继续维持双服务，也可以未来升级为 MQ + Worker 模式。

### 审计项 6：当前实施是否存在不可控风险

结论：可控。  
因为 Java 已经先抽象了 `AgentAiGateway`，Node 可以逐步接入，不需要推翻当前主系统。

---

## 二十、最终审计结论

综合业务特征、当前代码现状、后续扩展方向和工程可控性，`agent-server` 的最优方案确定为：

## 最终方案：`Java Core + Node AI Gateway`

并采用以下实施原则：

- 不回滚为旧 Node 主系统
- 不推翻现有 Java 主干
- 先补 Node AI Gateway
- 再迁移仓库目录
- 最终形成标准多应用仓库

这个方案在技术上是自洽的，在实施上是渐进可控的，在能力表达上也最符合你现在要构建“架构优秀后端项目”的目标。

---

