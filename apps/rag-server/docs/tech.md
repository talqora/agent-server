# `test/app.e2e-spec.ts` 报错说明

## 这次报错是什么

本次报错集中在 `test/app.e2e-spec.ts` 里的这段链式调用：

```ts
return request(app.getHttpServer())
  .get('/')
  .expect(200)
  .expect('Hello World!');
```

报错主要有两类：

1. `@typescript-eslint/no-unsafe-call`
2. `@typescript-eslint/no-unsafe-return`

它们的共同含义是：

- ESLint 在做“带 TypeScript 类型信息的静态检查”时，发现这里调用的对象类型没有被正确解析。
- 一旦调用目标的类型不清晰，后续 `.get()`、`.expect()`、最终 `return` 出去的值，都会被认为存在潜在不安全性。

这不是说代码运行时一定有 bug，而是“类型系统无法证明这段代码是安全的”。

## 本次问题的直接原因

原来的写法是：

```ts
import * as request from 'supertest';
import { App } from 'supertest/types';

let app: INestApplication<App>;
```

这里有两个关键问题。

### 1. `supertest` 的导入方式不对

`supertest` 的主导出本质上是一个可直接调用的函数，常见正确写法是：

```ts
import request from 'supertest';
```

而原来的：

```ts
import * as request from 'supertest';
```

在当前 `TypeScript + NodeNext + esModuleInterop` 配置下，推断出来的是“模块命名空间对象”。

模块命名空间对象可以理解成：

```ts
{
  default: ...,
  Test: ...,
  agent: ...
}
```

它是一个对象，不是一个可直接执行的函数，所以当代码写成 `request(...)` 时，TypeScript 会认为：

> 你在尝试把一个普通对象当函数调用。

因此会出现截图里的这条核心 TS 报错：

> 此表达式不可调用。类型没有调用签名。

一旦第一步 `request(...)` 的类型错了，后面的 `.get()`、`.expect()` 就都会连锁报错。

### 2. `INestApplication<App>` 这个泛型没有必要，还容易干扰类型理解

Nest 官方常见模板里一般直接写：

```ts
let app: INestApplication;
```

`app.getHttpServer()` 返回的是底层 HTTP Server 句柄，交给 `supertest` 即可。

这里额外引入 `supertest/types` 里的 `App` 泛型并不是必须的，而且会让测试文件的类型关系变得更复杂。对于当前这个简单 e2e 测试，去掉它更稳妥，也更符合官方模板。

## 修复后做了什么

修复后的关键改动只有两点：

```ts
import request from 'supertest';
let app: INestApplication;
```

本质上是在做两件事：

1. 让 `request` 被正确识别为 `supertest` 导出的可调用函数。
2. 让 `app.getHttpServer()` 与 `supertest` 的入参类型回到官方推荐的简单路径。

这样 ESLint 和 TypeScript 就都能正确推断这条调用链的类型。

## 这些概念分别是什么意思

### 1. E2E 测试

E2E 是 End-to-End，端到端测试。

它不是只测某个函数，而是尽量按“真实请求经过真实应用”的方式验证整个流程，例如：

1. 启动 Nest 应用
2. 获取 HTTP Server
3. 用 `supertest` 模拟发送 HTTP 请求
4. 校验响应状态码和响应内容

这比单元测试更接近真实运行场景。

### 2. `supertest`

`supertest` 是 Node.js 生态里常用的 HTTP 测试库。

它的作用是：

- 不需要真正把服务发布到外网端口
- 直接拿到应用的 HTTP server 实例
- 在内存里模拟请求
- 返回一个可链式断言的对象

所以这里的：

```ts
request(app.getHttpServer()).get('/').expect(200)
```

可以理解为：

“对这个应用的 HTTP 服务发一个 GET `/` 请求，并断言它应该返回 200。”

### 3. `INestApplication`

这是 NestJS 应用实例的接口类型。调用：

```ts
moduleFixture.createNestApplication()
```

会创建一个 Nest 应用对象，随后：

```ts
await app.init();
```

会完成模块初始化、控制器注册、路由装配等动作。

### 4. 静态检查

静态检查是“代码不运行，先在编辑阶段分析代码”。

这里实际有两层：

1. TypeScript 编译器检查类型是否成立
2. ESLint 基于 TypeScript 类型信息进一步检查是否存在“不安全调用”“不安全返回”等问题

也就是说，这些报错不是运行时报错，而是开发期的质量保护机制。

## 这些规则本质在做什么

### `no-unsafe-call`

这个规则要防止你去调用一个类型不明确的值。

例如下面这种思路就是危险的：

```ts
const x: any = something;
x();
```

因为 `x` 可能根本不是函数，但 `any` 会绕过类型系统，让问题拖到运行时才爆炸。

所以 `no-unsafe-call` 的本质是：

> 不允许在“类型系统无法确认可调用”的前提下执行函数调用。

### `no-unsafe-return`

这个规则要防止你从函数里返回一个不安全类型。

原因是：一旦危险类型被 return 出去，它就会继续污染调用方，导致更大范围的类型失真。

所以它的本质是：

> 不要把一个来源不明、类型不可靠的值继续向外传播。

## 它们发挥作用的原理

底层依赖的是 TypeScript 的类型信息。

当前项目的 ESLint 配置里启用了：

```ts
...tseslint.configs.recommendedTypeChecked
```

并且配置了：

```ts
parserOptions: {
  projectService: true,
  tsconfigRootDir: import.meta.dirname,
}
```

这意味着 ESLint 不是只看语法，而是会调用 TypeScript 的类型服务来理解：

- `request` 到底是什么
- `request(...)` 的返回值是什么
- `.get()` 是否真的存在
- `return` 出去的对象类型是否安全

也正因为如此，这类规则比普通语法规则更严格，也更有价值。

## 这次报错的完整传导过程

这次问题可以按下面的链路理解：

1. `import * as request from 'supertest'` 让 `request` 被推成“模块对象”
2. 模块对象没有调用签名，所以 `request(...)` 不成立
3. 由于第一步类型已坏，`request(...)` 的结果也无法可靠推断
4. 所以后面的 `.get()`、`.expect()` 被认为是对未知危险对象做成员访问和调用
5. 最终 `return request(...).get(...).expect(...)` 时，又触发 `no-unsafe-return`

可以看出，后续错误基本都是“首个类型错误的连锁反应”。

## 更底层一点：为什么 `import * as` 会出问题

这和 ES Module / CommonJS 互操作有关。

### CommonJS 和 ES Module

Node.js 生态里历史上大量包使用 CommonJS：

```js
module.exports = fn;
```

而现代 TypeScript / ESM 更常见的是：

```ts
export default fn;
```

这两套模块系统在“默认导出”“命名导出”“命名空间导入”上的语义并不完全一样。

`import * as request from 'supertest'` 的语义更接近：

> 把整个模块的所有导出收集成一个对象。

因此拿到的通常是“命名空间对象”，而不是默认导出的那个函数本身。

而 `import request from 'supertest'` 才是在当前配置下更符合 `supertest` 用法的写法。

## 本质是在测什么

这段测试的本质不是“测试 `supertest`”，而是测试：

- Nest 应用是否成功启动
- `/` 路由是否存在
- 这个路由是否返回 `200`
- 返回体是否是 `'Hello World!'`

也就是验证“HTTP 接口对外表现是否符合预期”。

## 作用过程的底层原理

可以把整个执行过程理解成下面几步：

1. `Test.createTestingModule()` 创建一个只用于测试的 Nest 模块容器
2. `.compile()` 让 Nest 完成依赖解析和模块编译
3. `createNestApplication()` 基于测试模块创建应用实例
4. `app.init()` 完成路由注册、中间件装载、生命周期钩子初始化
5. `app.getHttpServer()` 取到底层 Node HTTP Server
6. `supertest` 把这个 server 包装成一个可发请求、可断言响应的测试客户端
7. `.get('/')` 构造 GET 请求
8. `.expect(200)` 和 `.expect('Hello World!')` 对响应结果做断言

如果其中任一步类型没对齐，静态检查就会预警；如果逻辑没对齐，测试运行时就会失败。

## 为什么这种检查有必要

必要性主要有三点。

### 1. 提前暴露问题

如果没有这些规则，很多错误会拖到运行时才发现，例如：

- 把对象当函数调用
- 调用不存在的方法
- 错误的模块导入方式

### 2. 避免 `any` 污染

一旦测试代码里大量出现 `any` 或无法解析的类型，IDE 自动补全、重构、错误提示都会明显变差。

### 3. 保证测试代码质量

很多人只关注业务代码质量，忽略测试代码。但测试代码本身如果类型混乱，也会导致误报、漏报，甚至让错误测试“看起来在通过”。

## 相关扩展知识

### 1. 为什么测试代码也要严格类型化

因为测试代码不是一次性脚本，它也是项目代码的一部分。

测试如果写得不严谨，会出现两类问题：

1. 误以为覆盖到了场景，实际上没有测到关键路径
2. 测试本身因为类型错误或导入错误而变得脆弱

### 2. 链式调用为什么容易把错误放大

链式调用依赖前一步返回值的类型是正确的。

一旦第一环出错，后面整条链的类型都会失真，所以编辑器里经常会看到“一串连续红线”。

### 3. `await` 和 `return` 在 Jest 测试里的关系

这类测试常见两种写法：

```ts
return request(...).get(...).expect(...);
```

或者：

```ts
await request(...).get(...).expect(...);
```

它们都能告诉 Jest“这个测试是异步的，请等待 Promise 完成”。  
当前这段使用 `return` 是成立的，只要返回值类型被正确推断即可。

### 4. 为什么官方模板通常更稳

像 Nest 这种成熟框架，官方模板里的测试写法通常已经兼顾了：

- 类型兼容性
- 工具链兼容性
- 社区最佳实践

如果没有明确需求，优先靠近官方模板通常比自己补复杂泛型更安全。

## 需要注意的点

1. 在 `TypeScript + ESLint type checked` 项目里，模块导入方式非常重要，不能只看“运行起来像没问题”。
2. `import * as xxx` 不等于默认导入，尤其在 CommonJS / ESM 混用场景里要谨慎。
3. 看到一串 `unsafe-*` 报错时，优先找“第一个真正的类型错误”，后面的很多时候只是连锁反应。
4. 测试代码也应该遵守和业务代码同级别的类型规范。
5. 如果库本身提供了官方推荐写法，优先使用官方写法，能减少很多工具链兼容问题。

## 这次修复结论

这次修复并不是改业务逻辑，而是修正“模块导入方式和不必要的泛型声明”，让：

- TypeScript 能正确理解 `request` 是可调用函数
- ESLint 能正确分析整条链式调用的类型
- `supertest` 与 Nest e2e 测试回到标准用法

最终结果就是：代码行为不变，但类型系统恢复正常，编辑器报错消失，测试文件的静态安全性也更高。

---

# `agent-server` 后端中涉及的 Nest 语法、引入的包与工具总解释

下面这部分不是只解释某一行代码，而是把当前 `agent-server` 这个后端里**实际出现的 Nest 语法、常见 TypeScript 写法、Node/Web 运行时能力、第三方包、以及开发工具链**统一说明清楚。

## 一、先理解这个后端的大体结构

当前后端是一个标准的 **NestJS + TypeScript** 服务。

它的大致分层是：

1. `src/main.ts`
   负责启动应用。
2. `src/app.module.ts`
   负责把全局模块组织起来。
3. `src/modules/agent/agent.module.ts`
   负责注册 Agent 相关的控制器和服务。
4. `agent.controller.ts`
   负责 HTTP / SSE 接口入口。
5. `agent.service.ts`
   负责核心业务编排。
6. `agent-run-store.service.ts`
   负责运行状态、事件历史和 SSE 推送。
7. `resource-collection.service.ts`
   负责本地文件和网页资源采集。
8. `ollama.provider.ts`
   负责调用本地 Ollama 模型服务。
9. `agent-report.service.ts`
   负责落盘输出报告文件。

本质上，这就是一个典型的：

- **Controller** 接请求
- **Service** 做业务
- **Store / Provider / Utility Service** 提供能力
- **Module** 负责注册和装配

的 Nest 项目。

## 二、Nest 核心语法到底是什么

### 1. `NestFactory.create(AppModule)`

#### 这是什么

它来自 `@nestjs/core`，写在 `src/main.ts` 中：

```ts
const app = await NestFactory.create(AppModule);
```

#### 本质是在做什么

它的本质是：

**根据根模块 `AppModule` 创建一个 Nest 应用实例，并把整个模块图、依赖注入容器、路由系统、中间能力都初始化起来。**

#### 它发挥作用的原理

当你把 `AppModule` 交给 `NestFactory.create()` 之后，Nest 会：

1. 读取 `AppModule` 上的元数据。
2. 找到它 `imports` 的模块。
3. 收集所有 `controllers` 和 `providers`。
4. 建立依赖注入容器。
5. 生成路由映射。
6. 创建底层 HTTP 服务器适配层。

也就是说，这一步不是“new 一个类”那么简单，而是在构建整个应用运行时。

#### 更底层的原理

Nest 本质上是一个**建立在 TypeScript 装饰器元数据之上的 IoC/DI 框架**。

- **IoC**：控制反转，意思是对象不是你自己到处 `new`，而是交给框架统一管理。
- **DI**：依赖注入，意思是类依赖什么，由框架自动帮你注入。

`NestFactory.create(AppModule)` 会触发 Nest 的扫描器去分析装饰器元数据，例如：

- 哪些类是 `@Module`
- 哪些类是 `@Controller`
- 哪些类是 `@Injectable`
- 哪些 provider 需要注入到哪些类里

然后再把这些关系组装成可运行的应用。

#### 注意点

1. `create(AppModule)` 的入参通常是根模块，不是随便一个业务类。
2. 应用启动失败时，很多错误其实都发生在“模块扫描”和“依赖注入解析”阶段，而不是 `listen()` 阶段。
3. `NestFactory` 来自 `@nestjs/core`，而具体 HTTP 平台实现通常由 `@nestjs/platform-express` 提供。

### 2. `@Module()`

#### 这是什么

它来自 `@nestjs/common`，例如：

```ts
@Module({
  imports: [AgentModule],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
```

以及：

```ts
@Module({
  controllers: [AgentController],
  providers: [
    AgentService,
    AgentRunStoreService,
    OllamaProvider,
    ResourceCollectionService,
    AgentReportService,
  ],
})
export class AgentModule {}
```

#### 本质是在做什么

`@Module()` 的本质是：

**告诉 Nest：这一组控制器、服务、依赖，属于同一个功能边界。**

可以把它理解为“后端功能包”或者“依赖注册清单”。

#### 它发挥作用的原理

Nest 不会自动扫描整个项目里所有类，而是**从根模块开始**，沿着 `imports` 向下递归收集模块，再从每个模块里读取：

- `controllers`
- `providers`
- `imports`
- `exports`

从而建立完整的依赖关系图。

#### 更底层的原理

`@Module()` 本身也是一个装饰器。它会把配置对象挂到类的元数据上。Nest 在启动时通过反射读取这份元数据，再据此构建容器。

#### 注意点

1. 一个类要想被 Nest 作为 provider 管理，通常必须出现在某个模块的 `providers` 里。
2. 一个模块要想使用别的模块导出的 provider，往往需要通过 `imports` + `exports` 明确声明。
3. 当前项目里的 `AgentModule` 相当于一个功能边界清晰的业务模块。

### 2.1 `providers` 到底是什么

#### 这是什么

`providers` 是 `@Module({...})` 配置对象中的一个字段，例如当前项目里：

```ts
@Module({
  controllers: [AgentController],
  providers: [
    AgentService,
    AgentRunStoreService,
    OllamaProvider,
    ResourceCollectionService,
    AgentReportService,
  ],
})
```

#### 本质是在做什么

它的本质是：

**向 Nest 的依赖注入容器登记“这个模块里有哪些可被注入、可被复用的对象提供者”。**

这里“provider”不要只机械地理解成“服务类”，更准确地说，它是：

**一个能够向别的类提供依赖实例的注册项。**

在当前项目里，大多数 provider 恰好就是 class，例如：

- `AgentService`
- `AgentRunStoreService`
- `OllamaProvider`
- `ResourceCollectionService`
- `AgentReportService`

所以你会很容易把 `providers` 看成“服务列表”。这个理解在当前项目里基本成立，但概念上它比“服务列表”更广。

#### 它发挥作用的原理

当 Nest 启动模块时，会读取 `providers`，然后把这些 provider 注册进 IoC 容器。

后面如果某个类构造函数写了：

```ts
constructor(
  private readonly runStore: AgentRunStoreService,
  private readonly ollamaProvider: OllamaProvider,
) {}
```

Nest 就会去容器里找：

1. 有没有 `AgentRunStoreService`
2. 有没有 `OllamaProvider`

如果有，就把对应实例注入进去。

所以你可以把 `providers` 理解为：

**“这个模块向容器声明：这些东西由我提供，你们可以来注入使用。”**

#### 更底层的原理

更底层一点看，provider 其实是围绕 **token → value / factory / class instance** 这件事建立的。

最常见的简写写法是：

```ts
providers: [AgentService]
```

这实际上相当于一种更完整的注册形式：

```ts
providers: [
  {
    provide: AgentService,
    useClass: AgentService,
  },
]
```

也就是说：

- `provide` 是注入 token
- `useClass` 表示遇到这个 token 时，用哪个类来创建实例

Nest 除了支持 `useClass`，还支持：

- `useValue`
- `useFactory`
- `useExisting`

所以 provider 本质不是“某个特殊关键字魔法”，而是 Nest 的**依赖注册机制**。

#### 为什么这个概念很重要

很多初学者会把这些概念混在一起：

1. `provider`
2. `service`
3. `injectable`
4. `module`

它们其实不是一回事：

- `service`：只是社区习惯叫法，通常指承担业务逻辑的类。
- `@Injectable()`：说明这个类可以作为可注入对象。
- `providers`：把这些可注入对象正式注册到模块容器里。
- `module`：负责组织这些注册关系。

换句话说：

**`@Injectable()` 让类“有资格被注入”，`providers` 让类“真的被注册进容器”。**

#### 注意点

1. 不是写了 `@Injectable()` 就一定能注入成功，还必须出现在某个模块的 `providers` 中，或者被别的模块 `export` 后再 `import` 进来。
2. 当前项目里的这些 provider 默认大多是单例，因此像 `AgentRunStoreService` 这样的内存状态会被整个应用共享。
3. 如果未来你把某个能力拆成独立模块，却忘了 `export`，另一个模块即便 `import` 了也可能拿不到对应 provider。

### 3. `@Controller()`、`@Get()`、`@Post()`、`@Sse()`

#### 这是什么

这些都是 `@nestjs/common` 提供的路由装饰器。

例如：

```ts
@Controller('agent')
export class AgentController {
  @Post('runs')
  createRun(...) {}

  @Get('runs/:runId')
  getRun(...) {}

  @Sse('runs/:runId/stream')
  streamRun(...) {}
}
```

#### 本质是在做什么

它们的本质是：

**把某个类方法映射成 HTTP 路由处理器。**

其中：

- `@Controller('agent')` 指定控制器的公共路由前缀。
- `@Post('runs')` 表示处理 `POST /agent/runs`
- `@Get('runs/:runId')` 表示处理 `GET /agent/runs/:runId`
- `@Sse('runs/:runId/stream')` 表示处理 SSE 长连接接口

再叠加 `main.ts` 里的：

```ts
app.setGlobalPrefix('api');
```

最终真实路由会变成：

- `POST /api/agent/runs`
- `GET /api/agent/runs/:runId`
- `GET /api/agent/runs/:runId/stream`

#### 它发挥作用的原理

Nest 在启动时会扫描控制器方法上的这些装饰器，把它们注册到底层 HTTP 适配器中。

也就是说，**方法名本身不重要，装饰器元数据才重要**。

底层会记录：

1. HTTP 方法是什么。
2. 路径是什么。
3. 这个请求到来时应该调用哪个类实例的哪个方法。
4. 参数该如何提取。

#### 更底层的原理

如果从底层看，Nest 最终还是在底层 HTTP 框架上挂 handler。

只是 Nest 帮你把下面这些事情做了抽象：

- URL 匹配
- 参数解析
- 异常转响应
- 依赖注入
- 生命周期管理

你写的是声明式装饰器，Nest 在启动期把它转换为运行时路由表。

#### 注意点

1. 路由路径是可以层层叠加的：全局前缀 + 控制器前缀 + 方法前缀。
2. `@Sse()` 不是普通 JSON 接口，它走的是 `text/event-stream`。
3. 同一路径不要同时声明冲突的处理器，否则容易出现覆盖或难以排查的问题。

### 4. `@Body()` 与 `@Param()`

#### 这是什么

这两个也是参数装饰器：

```ts
createRun(@Body() body: Record<string, unknown>) {}
getRun(@Param('runId') runId: string) {}
```

#### 本质是在做什么

它们的本质是：

**告诉 Nest 从 HTTP 请求的哪个位置提取参数，并传给方法。**

- `@Body()`：从请求体里取数据。
- `@Param('runId')`：从路径参数里取 `runId`。

#### 它发挥作用的原理

当请求进入控制器时，Nest 会根据参数装饰器的元数据，自动去：

- `req.body`
- `req.params`
- `req.query`
- `req.headers`

等位置取值，再按顺序喂给方法参数。

#### 更底层的原理

本质上，这是一层**从底层请求对象到声明式参数列表的映射**。

不使用 Nest 时，你往往要自己写：

```ts
const body = req.body;
const runId = req.params.runId;
```

Nest 用参数装饰器把这一步抽象掉了。

#### 注意点

1. 现在这里只做了手动归一化和校验，没有引入 DTO + class-validator。
2. `Record<string, unknown>` 的含义是“这是个对象，但字段类型还不可信”，所以后面要自己做 `typeof`、`Array.isArray` 等检查。

### 5. `@Injectable()`

#### 这是什么

它也是 `@nestjs/common` 的装饰器，当前项目里 `AgentService`、`AgentRunStoreService`、`AgentReportService`、`OllamaProvider`、`ResourceCollectionService` 都用了它。

#### 本质是在做什么

它的本质是：

**把一个类声明为可被 Nest 注入容器管理的 provider。**

换句话说，Nest 才知道这个类可以被别的类依赖。

#### 它发挥作用的原理

当 Nest 发现一个 `@Injectable()` 类又被注册进 `providers` 后，就会为它创建实例，并在别的类构造函数需要它时进行注入。

例如：

```ts
constructor(
  private readonly runStore: AgentRunStoreService,
  private readonly ollamaProvider: OllamaProvider,
) {}
```

意思不是“语言自动懂了”，而是：

1. TypeScript 通过类型知道参数类型。
2. Nest 通过反射拿到这个构造函数参数类型。
3. 再去容器中找匹配的 provider 实例。
4. 注入进去。

#### 更底层的原理

这一切依赖于：

- 装饰器元数据
- `reflect-metadata`
- TypeScript 编译时生成的设计时类型信息

Nest 启动时会读取构造函数参数的元数据，例如“这个参数类型是 `AgentRunStoreService`”，然后按 token 去容器里解析实例。

#### 注意点

1. `@Injectable()` 不等于“一定能注入成功”，还得在模块里注册。
2. 当前默认 provider 生命周期通常是单例。
3. 单例服务里保存状态要小心线程模型和并发语义。这个项目里 `AgentRunStoreService` 用内存 `Map` 保存运行状态，就是一种单例内存状态。

### 6. `constructor(private readonly xxx: SomeService)`

#### 这是什么

这是 TypeScript 的**参数属性（parameter properties）**语法，不是 Nest 独有，但在 Nest 里非常常见。

例如：

```ts
constructor(private readonly agentService: AgentService) {}
```

#### 本质是在做什么

它同时做了两件事：

1. 声明一个类字段 `this.agentService`
2. 让构造函数参数接受注入值

#### 它发挥作用的原理

普通写法通常是：

```ts
private readonly agentService: AgentService;

constructor(agentService: AgentService) {
  this.agentService = agentService;
}
```

参数属性语法只是更简洁。

Nest 真正依赖的是“构造函数参数类型”，不是这个语法糖本身。

#### 注意点

1. `private readonly` 只是 TypeScript 层面的访问控制和只读约束。
2. 运行时的对象仍然是普通 JavaScript 对象，不存在真正的私有字段保护。

### 7. `BadRequestException`、`NotFoundException`、`ServiceUnavailableException`

#### 这是什么

这些来自 `@nestjs/common`，是 Nest 封装好的 HTTP 异常类。

#### 本质是在做什么

它们的本质是：

**用“抛异常”的写法来表达 HTTP 错误响应。**

例如：

- `BadRequestException` 对应 400
- `NotFoundException` 对应 404
- `ServiceUnavailableException` 对应 503

#### 它发挥作用的原理

你在业务代码里直接 `throw new BadRequestException('任务不能为空')`，Nest 的异常过滤体系会拦住它，并自动生成 HTTP 响应。

这就避免你在每个控制器里手写：

```ts
res.status(400).json(...)
```

#### 更底层的原理

Nest 内部有统一的异常处理层，会判断抛出的对象是否是 `HttpException` 家族；如果是，就按其中携带的状态码和响应体格式输出给客户端。

#### 注意点

1. 业务异常和系统异常最好区分开。
2. 如果抛的是普通 `Error`，通常会变成 500，除非你自定义异常过滤器。
3. 当前项目里 `OllamaProvider` 用 503 表示“依赖服务不可用”，语义是合理的。

### 8. `type MessageEvent`、`Observable<MessageEvent>`、`@Sse()`

#### 这是什么

在当前项目中，SSE 接口这样写：

```ts
@Sse('runs/:runId/stream')
streamRun(@Param('runId') runId: string): Observable<MessageEvent> {
  return this.agentService.streamRun(runId);
}
```

#### 本质是在做什么

它的本质是：

**返回一个可以持续发出多条消息的数据流，而不是一次性返回一个 JSON 对象。**

#### 它发挥作用的原理

Nest 对 `@Sse()` 的约定是：

- 如果你返回的是 `Observable<MessageEvent>`
- 那么 Observable 每 `next()` 一次
- Nest 就往 HTTP 响应流里写一帧 SSE 事件

`MessageEvent` 里的：

- `type` 对应 SSE 协议里的 `event:`
- `data` 对应 SSE 协议里的 `data:`

前端 `EventSource.addEventListener(type, ...)` 就能按事件名接住。

#### 更底层的原理

SSE 不是轮询，也不是 WebSocket。

它本质上是：

1. 浏览器发一个普通 HTTP GET。
2. 服务端不立刻结束响应。
3. 响应头声明为 `text/event-stream`。
4. 之后不断往同一条响应流里追加文本帧。
5. 浏览器边收边解析，再触发前端回调。

所以它是“基于 HTTP 的服务端单向推送”。

#### 注意点

1. SSE 很适合进度流、日志流、通知流这种“服务端持续推送”的场景。
2. 如果需要双向实时通信，通常更适合 WebSocket。
3. SSE 断线重连、代理超时、CORS、反向代理缓冲等问题，在生产环境要单独关注。

## 三、RxJS 在这里到底起了什么作用

### 1. `Observable`

#### 这是什么

`Observable` 来自 `rxjs`，可以理解为“未来会持续产生值的流”。

#### 本质是在做什么

它的本质是：

**把“一个一个到来的异步事件”包装成统一的数据流抽象。**

在这个项目里，它正好适合表示：

- 某个 run 的 SSE 事件流

#### 它发挥作用的原理

`new Observable((subscriber) => { ... })` 中：

- `subscriber.next(value)`：发一条值
- `subscriber.error(err)`：发错误并结束
- `subscriber.complete()`：正常结束

Nest 的 `@Sse()` 会订阅它，并把每次 `next` 转成 SSE 输出。

### 2. `Subject`

#### 这是什么

`Subject` 也来自 `rxjs`。它既像 Observable，又像一个可以主动往外推值的事件总线。

#### 本质是在做什么

在当前项目中：

**`Subject<AgentRunEvent>` 就是一条 run 对应的“实时广播通道”。**

#### 它发挥作用的原理

`publish(event)` 时：

1. 先把事件写进 `events` 历史数组。
2. 再 `subject.next(event)` 广播给当前已连接的订阅者。

`stream(runId)` 时：

1. 先重放历史 `events`
2. 再订阅 `subject`

这样就同时兼顾了：

- 晚连接能看到已发生事件
- 已连接能收到实时事件

这里的“**重放历史 `events`**”需要单独解释一下。

#### “重放历史”到底是什么意思

它不是“把时间倒流再执行一遍真正的业务逻辑”，也不是“重新向 Ollama 发一遍请求”，而是：

**把这个 run 之前已经记录在内存数组 `run.events` 里的事件，再按原顺序重新发给新连上的 SSE 客户端。**

例如：

1. 某个 run 已经先后产生了：
   - `run_started`
   - `plan_ready`
   - `resource_collected`
2. 这时前端才刚建立 SSE 连接，或者连接断开后重新连上。
3. `stream(runId)` 会先遍历 `run.events`：

```ts
for (const event of run.events) {
  subscriber.next({
    type: event.type,
    data: event,
  });
}
```

4. 于是前端虽然“晚到”，但仍然能补收到前面已经发生过的这些事件。

#### 本质是在做什么

本质上它是在做：

**“新订阅者补历史”**。

这样就避免出现一种很差的情况：

- 任务已经跑了一半
- 你这时才打开页面或刚连上 SSE
- 结果前端完全不知道前面发生过什么

通过“重放历史”，前端可以先补齐过去，再继续接实时事件。

#### 为什么需要这样做

因为 `Subject` 只负责“从现在开始往后推”。

如果你只订阅 `subject`，那么订阅发生之前已经推过的事件，默认是收不到的。  
所以当前项目用了“两段式”：

1. 先手动遍历 `run.events`，补发历史
2. 再订阅 `subject`，接收未来事件

#### 更底层的理解

可以把它类比成聊天记录：

- `events` 像“历史消息记录”
- `subject` 像“正在实时收到的新消息”

新用户进群时：

1. 先把之前聊天记录补给他看
2. 再让他开始实时接收新消息

这就是这里“重放历史”的真实含义。

#### 注意点

1. 这里重放的是**内存里已记录的事件对象**，不是重新执行真实业务步骤。
2. 如果事件很多，重放会带来一定响应开销；当前项目事件量较小，所以问题不大。
3. 当前历史只存在内存里，所以进程重启后就没有“历史可重放”了。

#### 更底层的原理

如果没有 `Subject`，你就得自己维护“当前所有连接”列表，再手动遍历推送。`Subject` 本质上帮你做了一个多播发布器。

#### 注意点

1. 现在这个状态存储是进程内内存级的，不是持久化队列。
2. 进程重启后，`Map` 和 `Subject` 里的状态都会丢失。
3. 如果以后需要多实例部署，内存 `Map` 就不够了，需要 Redis、数据库或消息队列之类的共享状态。

## 四、当前项目里常见的 TypeScript / JavaScript 语法是什么意思

### 3. `Record<string, unknown>`

这表示“键是字符串，值暂时未知的对象”。

本质上是在表达：

**这个对象来自外部输入，所以现在还不能假设它是安全的。**

这也是为什么后面要手动做：

- `typeof body.task === 'string'`
- `Array.isArray(body.urls)`

这类收窄。

### 4. `Pick<StoredRun, 'id' | 'status' | ...>`

这是一种类型投影，意思是“从 `StoredRun` 里只选出一部分字段组成新类型”。

本质作用是减少重复写类型，同时明确函数只返回某个对象的部分内容。

## 五、后端里用到的 Node / Web 运行时能力是什么

### 1. `process.env`

#### 这是什么

Node 进程的环境变量对象。

#### 本质是在做什么

用外部配置影响程序行为，而不是把配置写死在代码里。

例如：

- `PORT`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `AGENT_MAX_FILES`

#### 注意点

1. `process.env` 里的值默认都是字符串或 `undefined`。
2. 所以代码里经常要写：

```ts
Number(process.env.AGENT_MAX_FILES ?? 12)
```

来做显式转换。

### 2. `process.cwd()`

它表示当前 Node 进程启动时的工作目录。  
`agent-report.service.ts` 用它来拼默认输出目录。

### 3. `randomUUID()` 来自 `node:crypto`

#### 本质

用于生成全局唯一标识。  
当前项目里它既用于生成 `runId` 的随机后缀，也用于资源项的 `id`。

#### 为什么要用它

因为 UUID 碰撞概率极低，适合做临时唯一 ID。

### 4. `node:fs/promises`

当前用到了：

- `mkdir`
- `stat`
- `writeFile`
- `readFile`
- `readdir`

#### 本质是在做什么

这些都是 Node 的异步文件系统 API，用 Promise 形式操作磁盘。

#### 在项目中的作用

- `mkdir`：创建输出目录
- `writeFile`：写报告文件
- `stat`：读文件元信息
- `readFile`：读本地文本资源
- `readdir`：遍历目录

#### 注意点

1. 这是 I/O 操作，不是纯内存计算，性能与磁盘、权限、路径有效性有关。
2. 很多地方用了 `try/catch` 后静默跳过，意味着项目当前更偏向“尽量继续采集”，而不是“有一个文件失败就整体失败”。

### 5. `Dirent` 与 `Stats`

它们分别表示：

- `Dirent`：目录项信息，例如是不是文件、是不是目录。
- `Stats`：文件状态信息，例如大小、时间等。

本质上是文件系统元数据对象。

### 6. `node:path`

当前用到了：

- `path.resolve`
- `path.join`
- `path.basename`
- `path.extname`

#### 本质是在做什么

它本质上是跨平台的路径拼接与解析工具，避免你手写斜杠导致路径错误。

#### 注意点

Windows 和 Unix 路径分隔符不同，所以在 Node 服务里尽量用 `path`，不要自己拼字符串。

### 7. `fetch`、`AbortController`、`URL`

#### `fetch`

这是现代 Web/Node 运行时提供的 HTTP 请求 API。

在当前项目中它被用于：

1. 调用 Ollama 的 `/api/chat`
2. 拉取网页内容做资源采集

#### `AbortController`

它的本质是“取消异步请求的控制器”。

当前代码里是用：

```ts
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), timeoutMs);
```

来实现超时中断。

#### `URL`

用于解析和校验 URL。  
如果 `new URL(rawUrl)` 抛错，就说明不是合法 URL。

#### 更底层的原理

`AbortController` 会向 `fetch` 传入一个 `signal`。  
一旦 `abort()` 被调用，运行时会中断该请求，并让 `fetch` 抛异常。

#### 注意点

1. 超时是调用方自己组合出来的，不是 `fetch` 自动带超时。
2. URL 合法不代表目标站点可访问。
3. 生产环境还要考虑 DNS、TLS、代理、证书、重试等问题。

## 六、第三方包在这个后端里分别做什么

### 1. `@nestjs/common`

#### 这是什么

Nest 最常用的公共能力包。

#### 当前项目里它提供了什么

- `@Module`
- `@Controller`
- `@Injectable`
- `@Get`
- `@Post`
- `@Sse`
- `@Body`
- `@Param`
- `BadRequestException`
- `NotFoundException`
- `ServiceUnavailableException`
- `MessageEvent` 类型

#### 本质

它相当于 Nest 的“日常开发主工具箱”。

### 2. `@nestjs/core`

主要提供 `NestFactory`。  
它更偏向 Nest 的核心启动能力和框架内部机制。

### 3. `@nestjs/platform-express`

#### 这是什么

这是 Nest 当前项目默认依赖的 HTTP 平台适配器。

#### 本质是在做什么

Nest 不是直接裸写 Node HTTP，而是通过平台适配层运行在 Express 之上。

也就是说，你虽然平时写的是 Nest 风格代码，但底层真正接住 HTTP 请求的，通常还是 Express 这一层。

这里你问得非常对，**Express 本身当然也是 Node.js 生态里的 Web 框架**。  
更准确的表述应该是：

- **Node.js** 是运行时，不是 Web 框架。
- **Express** 是构建在 Node.js 运行时之上的 Web 框架。
- **Nest** 也是构建在 Node.js 运行时之上的后端框架，但它默认不是直接裸用 Node HTTP，而是通常借助 **Express 作为底层 HTTP 平台适配器**。

#### 更准确地说，Nest 和 Express 到底是什么关系

可以把这三层理解成：

1. **Node.js**
   提供 JavaScript 运行环境、网络能力、文件系统、事件循环。
2. **Express**
   在 Node.js 之上封装了 HTTP 路由、中间件、请求响应对象等 Web 开发能力。
3. **Nest**
   再往上提供模块化、依赖注入、装饰器路由、守卫、拦截器、管道、异常过滤器等更高层的工程化结构。

所以不是“Express 不是框架”，而是：

**Express 是更底层、更轻量的 Node Web 框架；Nest 是更上层、更强调架构和组织方式的后端框架。**

#### 为什么说“底层真正接住 HTTP 请求的通常还是 Express”

因为当前项目依赖里有：

- `@nestjs/platform-express`

这表示 Nest 最终会把：

- 路由注册
- 请求对象封装
- 响应发送
- 中间件链路

这些 HTTP 层工作，落到 Express 适配器上。

也就是说，当浏览器或前端客户端发来一个 HTTP 请求时，真正最先在 HTTP 平台层接住它的，通常是 Express 这层；Nest 再在这个基础上加上自己的控制器、依赖注入、异常系统等高层抽象。

#### 那 Nest 和 Express 谁“更大”

不是简单的“谁替代谁”，而是抽象层次不同：

- Express 更接近 HTTP 和中间件本身。
- Nest 更接近“工程化应用框架”。

你可以把 Express 理解为更灵活但更原始的底层框架；把 Nest 理解为建立在这些平台能力之上的高级组织层。

#### 一个更直观的类比

如果把 Web 服务比作盖房子：

- Node.js 像土地和基础设施
- Express 像砖、水泥、钢筋和基础施工方式
- Nest 像整套建筑设计规范、分层图纸和施工管理体系

所以你写 Nest 时，经常感觉自己没直接碰 Express；但在默认平台下，Nest 的很多 HTTP 能力确实是通过 Express 承接的。

#### 注意点

以后如果换成 Fastify，很多业务代码可以不变，因为 Nest 把平台差异抽象掉了。

### 4. `reflect-metadata`

#### 这是什么

这是 TypeScript 装饰器生态里非常关键的元数据支持库。

#### 本质是在做什么

它让“装饰器附加的元数据”和“设计时类型信息”可以在运行时被读取。

Nest 的依赖注入、路由扫描、参数解析，很多都依赖这层能力。

#### 更底层的原理

JavaScript 本身原生并不自动提供完整的类型反射信息。`reflect-metadata` 相当于给运行时补了一层元数据存储/读取机制。

### 6. `cheerio`

#### 这是什么

一个服务端 HTML 解析库，经常被称为“服务端版 jQuery 风格 API”。

#### 当前项目里它在做什么

```ts
const $ = load(html);
$('script, style, noscript').remove();
const title = $('title').first().text().trim();
const text = $('body').text().replace(/\s+/g, ' ').trim();
```

它的本质是：

**把 HTML 字符串解析成可遍历、可选择的 DOM 结构，然后提取正文文本。**

#### 为什么它能起作用

因为网页源码本质上就是文本。`cheerio` 先把文本解析成 DOM 树，再提供 CSS 选择器风格接口让你查节点、删节点、取文本。

#### 注意点

1. `cheerio` 不执行页面 JavaScript，所以它只适合静态 HTML 或 SSR 页面。
2. 如果内容是前端运行后动态注入的，直接 `fetch HTML` 可能拿不到最终页面文本。
3. 这类正文提取通常比较粗糙，真实生产里可能需要更复杂的正文抽取策略。

## 七、当前项目中的具体业务类，本质上分别是什么

### 1. `AgentController`

它是**协议入口层**。  
负责把 HTTP/SSE 请求转成业务调用，并做入参归一化与基础校验。

### 2. `AgentService`

它是**业务编排层**。  
负责把“规划、采集、摘要、聚合、写报告、发事件”串成一个完整流程。

### 3. `AgentRunStoreService`

它是**运行态内存状态中心**。  
负责：

- 按 `runId` 保存状态
- 存事件历史
- 给 SSE 提供重放和实时广播

### 4. `OllamaProvider`

它是**外部模型服务适配层**。  
本质上是在把“调用本地 Ollama HTTP 接口”的细节封装起来，让业务层直接调用 `completeText` / `completeJson`。

### 5. `ResourceCollectionService`

它是**资源采集层**。  
把“目录遍历、文件过滤、文本截断、网页抓取、HTML 提取”都封在一起。

### 6. `AgentReportService`

它是**产物输出层**。  
负责把运行结果写成：

- `report.md`
- `report.json`
- `sources.json`

## 八、开发工具链里的包和工具都是什么意思

下面这部分主要来自 `package.json`。

### 1. `@nestjs/cli`

Nest 官方命令行工具。  
用于 `nest build`、`nest start` 等命令。

### 2. `@nestjs/schematics`

Nest 的代码生成模板工具。  
通常用于脚手架生成模块、控制器、服务等。

### 3. `@nestjs/testing`

Nest 的测试辅助库。  
用于在测试环境中创建测试模块、测试应用实例。

### 4. `typescript`

TypeScript 编译器本体。  
负责类型检查和把 TS 编译成 JS。

### 5. `ts-node`

在 Node 环境直接执行 TypeScript 的工具。  
常用于测试、脚本、调试场景。

### 6. `ts-jest`

Jest 和 TypeScript 之间的桥接层。  
让 Jest 能理解并运行 `.ts` 测试文件。

### 7. `ts-loader`

常用于构建流程里处理 TypeScript。  
当前项目未必在业务代码中直接感知它，但它属于 TS 构建工具链的一部分。

### 8. `tsconfig-paths`

用于让运行时理解 `tsconfig` 里的路径别名配置。  
尤其在调试或测试命令里常见。

### 9. `eslint`、`typescript-eslint`

#### 本质

静态代码质量检查工具。

- `eslint`：规则执行器
- `typescript-eslint`：让 ESLint 能理解 TypeScript 语法与类型信息

它们不是在运行时起作用，而是在开发阶段帮助你更早发现问题。

### 10. `prettier`

代码格式化工具。  
它的目标是统一代码风格，而不是检查业务逻辑对错。

### 11. `jest`

JavaScript/TypeScript 常用测试框架。  
负责执行测试、断言、mock、统计结果等。

### 12. `supertest`

HTTP 接口测试库。  
让你在测试里像发真实请求一样去测 Nest 应用。

### 13. `source-map-support`

让运行时报错堆栈更容易映射回 TypeScript 源码位置。  
本质上是改善调试体验。

### 14. `@types/node`、`@types/jest`、`@types/supertest`、`@types/express`

这些是类型定义包。  
它们本质上是“给 TypeScript 用的说明书”，告诉编译器这些库的 API 长什么样。

### 15. `globals`、`@eslint/js`、`@eslint/eslintrc`、`eslint-config-prettier`、`eslint-plugin-prettier`

这些属于 ESLint / Prettier 周边工具链。

它们分别用于：

- 提供基础 ESLint 规则集
- 兼容新旧 ESLint 配置方式
- 处理全局变量配置
- 让 ESLint 与 Prettier 协同工作
- 把 Prettier 格式问题接入 ESLint 流程

## 九、`main.ts` 里的应用级配置是什么意思

### 1. `app.enableCors({ origin: true })`

#### 这是什么

开启 CORS。

#### 本质是在做什么

告诉浏览器：允许跨源前端访问这个后端。

#### 为什么有必要

当前前端 `AiAgent` 和后端 `agent-server` 很可能是不同端口，不同端口在浏览器眼里就是不同源。

如果不开 CORS，浏览器会拦截跨域请求。

#### 注意点

`origin: true` 表示动态回显来源，开发期方便，但生产环境通常应该更精确地限制允许来源。

### 2. `app.setGlobalPrefix('api')`

它的本质是给所有路由统一加前缀，便于：

- 区分 API 与静态页面
- 做版本管理
- 让路由结构更清晰

### 3. `app.listen(process.env.PORT ?? 3000)`

它的本质是：

**让应用开始监听某个 TCP 端口，对外提供 HTTP 服务。**

更底层一点，就是底层 HTTP 服务器开始接受网络连接。

## 十、为什么这些概念有必要理解

如果只会“照着模板写”，短期内也许能跑通，但一旦遇到下面这些问题就会很难排查：

1. 为什么某个 service 注入失败。
2. 为什么某个路由根本没生效。
3. 为什么 SSE 能持续推送，而普通 `return {}` 不行。
4. 为什么 `throw new BadRequestException()` 会自动变成 400。
5. 为什么 `process.env` 取出来要自己转数字。
6. 为什么 `cheerio` 抓不到动态页面内容。
7. 为什么内存 `Map` 在单机能跑，多实例部署就出问题。

理解这些概念，本质上是在理解：

**这个后端不是“很多文件碰巧连在一起”，而是 Nest、TypeScript、Node、RxJS、HTTP 协议、文件系统、以及开发工具链共同协作出来的一套运行机制。**

## 十一、与当前项目强相关的注意点

### 1. `AgentRunStoreService` 现在是内存态

这意味着：

1. 进程重启后运行历史会丢失。
2. 只能天然适合单进程。
3. 如果未来要水平扩展，必须考虑共享状态方案。

### 2. SSE 很适合这个场景，但要注意部署环境

开发环境里 SSE 往往比较顺；生产里如果前面有 Nginx、网关、CDN，需要注意：

- 连接超时
- 代理缓冲
- CORS
- keep-alive
- 断线重连行为

### 3. `cheerio` 不是浏览器

它不会执行前端 JS，所以“页面源码里没有正文”的站点，抓取结果可能很差。

### 4. `fetch` 超时是手动拼出来的

项目里用了 `AbortController + setTimeout` 做超时控制。  
这是一种常见做法，但不等于自动重试，也不等于网络一定可靠。

### 5. 目前没有引入更重的 Nest 校验体系

当前控制器使用的是手动归一化方式，而不是：

- DTO
- `class-validator`
- `ValidationPipe`

这意味着当前实现更轻量，但规则扩展时也更依赖手写校验逻辑。

## 十二、一句话总总结

当前 `agent-server` 的核心运行模式可以总结为：

**Nest 用模块、控制器、服务和依赖注入把结构搭起来；Node 提供文件系统、网络和环境变量能力；RxJS 帮 SSE 建立流；`fetch` 和 `cheerio` 负责外部资源获取；Ollama 负责模型推理；工具链则保证构建、格式化、静态检查和测试能顺利进行。**

---

# `lint-staged.config.mjs` 被 ESLint Project Service 误判为不在项目中的问题记录

## 问题描述

本次报错发生在根目录配置文件 `lint-staged.config.mjs` 上，错误信息为：

```txt
Parsing error: D:\agent-server\lint-staged.config.mjs was not found by the project service. Consider either including it in the tsconfig.json or including it in allowDefaultProject.
```

报错文件内容本身非常简单：

```js
export default {
  '*.{js,ts}': ['eslint --fix', 'prettier --write'],
  '*.{json,md,yml,yaml}': ['prettier --write'],
};
```

也就是说，问题并不是这份 `lint-staged` 配置写错了，而是 **ESLint 在解析这个 `.mjs` 文件时，错误地把它当成了必须受 TypeScript project service 管理的“类型感知文件”**。

## 问题原因

这次问题的根因有两层。

### 1. 当前 ESLint 配置启用了 TypeScript 的 project service

项目中的 `eslint.config.mjs` 原本启用了：

```js
parserOptions: {
  projectService: true,
  tsconfigRootDir: import.meta.dirname,
}
```

这意味着：

1. `typescript-eslint` 不只是做语法检查。
2. 它还会尝试为文件建立 TypeScript 项目上下文。
3. 某些规则会依赖“类型信息”才能运行。

这类配置很适合真正属于 TS 项目的源码文件，例如：

- `src/**/*.ts`
- `test/**/*.ts`

但不一定适合项目根目录下那些独立的 JS / MJS 工具配置文件。

### 2. `lint-staged.config.mjs` 不是 TypeScript 项目服务要管理的源码文件

`lint-staged.config.mjs` 是：

- 一个 `.mjs` 文件
- 根目录工具配置文件
- 不参与当前 TS 项目的源码编译

它本质上属于“Node 运行的工具配置”，不是“TypeScript 项目里的业务源码”。

当 `typescript-eslint` 的 project service 试图为它建立类型项目上下文时，就会发现：

> 这个文件不在当前 TypeScript 项目管理的范围里。

于是产生了解析错误。

### 3. 第一次尝试只加 `allowDefaultProject`，虽然方向对，但还不够稳

最开始的修法是尝试在 `projectService` 里给 `lint-staged.config.mjs` 加默认项目兜底。

这个思路并不完全错，但在当前 ESLint 组合配置下，还有两个现实问题：

1. `.mjs` 文件本身更适合按“普通 JS 配置文件”处理，而不是继续让 type-checked 规则参与。
2. 项目里还额外启用了依赖类型信息的规则：
   - `@typescript-eslint/no-floating-promises`
   - `@typescript-eslint/no-unsafe-argument`

即便 parser 层不再报原始 project service 错误，这些规则依旧可能对 `.mjs` 文件继续要求类型信息。

所以仅靠 `allowDefaultProject` 在这个项目里不够彻底。

## 解决方案

最终采用的方案是：

**把 `**/*.mjs` 配置文件从 type-checked TypeScript 规则体系中单独分离出来，按普通 Node ESM 配置文件处理。**

具体做了两件事：

1. 对 `**/*.mjs` 使用 `typescript-eslint` 的 `disableTypeChecked` 配置。
2. 对 `**/*.mjs` 关闭当前自定义里依赖类型信息的规则：
   - `@typescript-eslint/no-floating-promises`
   - `@typescript-eslint/no-unsafe-argument`

同时保留：

- 普通 ESLint 推荐规则
- Prettier 规则
- Node 全局变量环境

这样 `.mjs` 仍然会被 lint，但不会再被错误地当成需要 TS 项目类型服务的文件。

## 解决问题的每一步及详细解释

### 第一步：先真实复现问题，而不是只看 IDE 提示

执行：

```bash
pnpm exec eslint "lint-staged.config.mjs"
```

得到最初的关键报错：

```txt
Parsing error: D:\agent-server\lint-staged.config.mjs was not found by the project service.
```

这一步的意义是：

1. 确认问题不只是编辑器缓存。
2. 确认是 ESLint 规则链路里的真实问题。
3. 把排查重心放在 `eslint.config.mjs` 上，而不是 `lint-staged.config.mjs` 内容本身。

### 第二步：检查现有 ESLint 配置，定位到 `projectService: true`

查看 `eslint.config.mjs` 后发现，全局启用了：

```js
parserOptions: {
  projectService: true,
  tsconfigRootDir: import.meta.dirname,
}
```

这说明 ESLint 正在以“带 TypeScript 类型信息”的方式处理文件。

这一步的核心判断是：

**问题不是 `.mjs` 语法错误，而是 `.mjs` 文件被送进了不合适的解析模式。**

### 第三步：验证 `typescript-eslint` 是否提供关闭 type-checked 的官方配置

为了避免拍脑袋硬配，我检查了 `typescript-eslint` 当前版本可用配置，确认存在：

```txt
disableTypeChecked
```

这一步的意义是：

1. 尽量使用官方提供的配置能力，而不是手写一堆脆弱的 parser hack。
2. 保证解决方案与当前工具链兼容。

### 第四步：给 `**/*.mjs` 增加单独 override，关闭 type-checked 解析

在 `eslint.config.mjs` 中加入：

```js
{
  files: ['**/*.mjs'],
  extends: [tseslint.configs.disableTypeChecked],
  languageOptions: {
    sourceType: 'module',
    globals: {
      ...globals.node,
    },
    parserOptions: {
      projectService: false,
    },
  },
}
```

这一步的本质是：

**告诉 ESLint：遇到 `.mjs` 时，不要再试图把它纳入 TS project service。**

同时：

- `sourceType: 'module'` 是因为 `.mjs` 本来就是 ESM 语义。
- `globals.node` 是因为这类配置文件运行在 Node 环境里。

### 第五步：继续验证，发现还有依赖类型信息的规则报错

在加入 `.mjs` override 之后，再次执行 ESLint，出现了新的错误：

```txt
Error while loading rule '@typescript-eslint/no-floating-promises':
You have used a rule which requires type information, but don't have parserOptions set to generate type information for this file.
```

这一步非常重要，因为它说明：

1. parser 层的问题虽然处理了。
2. 但规则层仍然有 type-aware 规则在对 `.mjs` 生效。

也就是说，这不是单一配置点的问题，而是**解析层和规则层都要一起处理**。

### 第六步：对 `.mjs` 单独关闭依赖类型信息的规则

继续增加一个 `.mjs` 专属规则覆盖：

```js
{
  files: ['**/*.mjs'],
  rules: {
    '@typescript-eslint/no-floating-promises': 'off',
    '@typescript-eslint/no-unsafe-argument': 'off',
  },
}
```

这一步的本质是：

**让这类配置文件只接受适合它的 lint 规则，不再强行使用依赖 TS 类型系统的规则。**

### 第七步：再次执行 ESLint，确认解析错误已经消失

再次执行：

```bash
pnpm exec eslint "lint-staged.config.mjs"
```

此时 project service 的解析错误已经消失，只剩下：

```txt
prettier/prettier
Insert `⏎`
```

这一步说明：

1. 真正的“解析错误”已经被修复。
2. 剩下只是普通格式问题，与项目服务无关。

## 方案有效的底层原理

### 1. 为什么会报 “was not found by the project service”

`typescript-eslint` 在启用 `projectService: true` 后，会尝试把当前文件交给 TypeScript 项目服务处理。

TypeScript 项目服务的思路是：

1. 找到与文件关联的 TS 项目上下文。
2. 建立类型信息。
3. 让需要类型信息的 ESLint 规则可运行。

但 `lint-staged.config.mjs` 这种文件：

- 不属于当前 TS 源码集合
- 不应该强依赖 TS 类型项目

所以 project service 无法给它建立预期上下文，就报了“找不到这个文件对应项目”的错误。

### 2. 为什么 `disableTypeChecked` 有效

`disableTypeChecked` 的作用不是“关闭所有 lint”，而是：

**关闭需要 TypeScript 类型信息参与的那一层能力。**

也就是说：

- 普通语法检查仍然可以做
- Prettier 仍然可以做
- Node 环境规则仍然可以做
- 但不再要求这份 `.mjs` 文件必须属于某个 TS 项目

这就和文件本身的性质匹配上了。

### 3. 为什么还要额外关闭 `no-floating-promises` / `no-unsafe-argument`

因为这些规则属于**依赖类型信息的规则**。  
即使 parser 已经不再通过 project service 给 `.mjs` 供类型信息，只要规则仍启用，它们就会继续报“没有类型信息不能运行”。

所以真正完整的解决方案必须同时满足：

1. parser 不再强求 `.mjs` 走 TS project service
2. rules 里也不再对 `.mjs` 启用 type-aware 规则

### 4. 为什么不把 `lint-staged.config.mjs` 强行塞进 `tsconfig.json`

理论上可以这样做，但在当前项目里并不是最自然的方案。

原因是：

1. `lint-staged.config.mjs` 不是 TypeScript 业务源码。
2. 它只是一个 Node 工具配置文件。
3. 把这类文件强行纳入 TS 项目，容易让“源码项目”和“工具配置项目”边界变模糊。

因此更合理的处理方式是：

**承认它就是一个独立的 `.mjs` 配置文件，并给它单独一套更合适的 lint 处理路径。**

## 需要注意的点

1. 以后如果项目根目录再新增类似文件，例如：
   - `commitlint.config.mjs`
   - `vitest.config.mjs`
   - `prettier.config.mjs`
   那么它们也可能需要复用同类 `.mjs` override 逻辑。

2. 这类文件通常更适合按“Node 配置文件”处理，而不是按“TS 业务源码”处理。

3. 如果以后你把 ESLint 规则进一步拆分，建议把：
   - Type-aware TS 规则
   - JS/MJS 配置文件规则
   明确分组，否则后续还会出现类似冲突。

4. 如果命令行已通过，但 IDE 仍显示旧错误，很多时候只是编辑器的 ESLint 诊断缓存还没刷新，不代表修复无效。

## 这次修复结论

这次问题不是 `lint-staged.config.mjs` 内容写错，也不是 `lint-staged` 工具本身有问题，而是：

**带 TypeScript 类型信息的 ESLint 配置把一个独立的 `.mjs` 配置文件错误地纳入了 project service 管理范围。**

最终修复方式是：

1. 为 `**/*.mjs` 单独关闭 type-checked 解析。
2. 为 `**/*.mjs` 关闭依赖类型信息的规则。
3. 修复该文件自身的 Prettier 格式问题。

最终验证结果：

```bash
pnpm exec eslint "lint-staged.config.mjs"
```

通过，`exit code 0`。

---

# ESLint 是怎么检测“代码是否正确”的

## 先说结论：ESLint 并不是在“运行你的代码”

很多人第一次接触 ESLint 时，会误以为它像测试框架一样真的去执行代码，然后判断对不对。  
其实不是。

ESLint 的核心工作方式是：

**把源码解析成结构化语法树（AST），然后用一组规则去遍历这棵树，检查代码结构、写法、上下文和一部分类型信息，看它是否违反约定。**

所以它检测的“正确”，严格说并不是：

- 程序运行结果一定正确

而是：

- 语法是否成立
- 写法是否符合规则
- 是否存在明显危险模式
- 在 TypeScript 场景下，类型信息能否证明这段代码安全

换句话说，ESLint 更接近：

**静态代码分析器**

而不是：

**运行时验证器**

## 一、必要概念 / 名词解释 / 背景知识

### 1. 什么叫“静态分析”

静态分析的意思是：

**不运行程序，只看源码本身，就尝试判断问题。**

例如下面这段代码：

```ts
const value = foo.bar();
```

ESLint 不需要真的运行 `foo.bar()`，也不需要真的等程序执行到这一行。  
它只要读源码，就可以分析：

1. 这里是不是合法语法
2. `foo` 是否未定义
3. 某些规则是否禁止这种写法
4. 如果有类型信息，`foo.bar()` 是否可能是不安全调用

### 2. 什么是 AST（Abstract Syntax Tree，抽象语法树）

这是理解 ESLint 的核心概念。

当你写：

```ts
const sum = a + b;
```

对人来说，它就是一行代码。  
但对 ESLint 来说，它会先被解析成一种“树状结构”，大概像这样：

```txt
VariableDeclaration
  VariableDeclarator
    Identifier(sum)
    BinaryExpression(+)
      Identifier(a)
      Identifier(b)
```

也就是说，ESLint 不是按“字符串匹配”检查代码，而是按**语法结构**检查代码。

这也是为什么它能区分：

- 变量声明
- 函数调用
- Promise 表达式
- import/export
- class
- decorator

等不同代码结构。

### 3. 什么是 parser（解析器）

ESLint 自己不是直接理解所有语言特性的。  
它需要 parser 把源码转成 AST。

在普通 JS 项目里，ESLint 默认 parser 足够处理很多情况。  
但在 TypeScript 项目里，一般会使用 `typescript-eslint` 提供的 parser。

也就是说，ESLint 的第一步通常是：

1. 读取文件文本
2. 交给 parser
3. parser 产出 AST
4. ESLint 规则再基于 AST 进行分析

### 4. 什么是 rule（规则）

ESLint 真正“检查问题”的执行单元就是 rule。

例如：

- `no-unused-vars`
- `no-undef`
- `@typescript-eslint/no-floating-promises`
- `@typescript-eslint/no-unsafe-argument`
- `prettier/prettier`

每条 rule 都可以理解成一个小程序：

**它知道自己应该监听哪类语法节点，并在节点出现时做检查。**

## 二、ESLint 本质上是在做什么

它本质上在做三件事：

1. **把代码结构化**  
   从文本变成 AST。

2. **把规则应用到语法结构上**  
   看代码有没有违反规范或潜在问题。

3. **输出诊断结果，必要时自动修复**  
   比如 warning、error，或者 `--fix` 自动修改部分代码。

所以 ESLint 并不是“判断程序业务逻辑完全正确”，而是在回答这种问题：

- 这段写法是否违反团队规则？
- 这段代码是否存在已知危险模式？
- 这个变量是不是没用？
- 这个 Promise 是否没处理？
- 这个参数传递是不是类型不安全？

## 三、ESLint 发挥作用的原理

### 第一步：读取文件

比如你执行：

```bash
eslint "src/**/*.ts"
```

ESLint 先会根据命令行参数、glob、ignore 配置，确定哪些文件需要处理。

在你这个项目里，`package.json` 里的 lint 命令就是：

```json
"lint": "eslint \"{src,apps,libs,test}/**/*.ts\" --fix"
```

它的意思是：

- 只处理 `src`、`apps`、`libs`、`test` 这些目录下的 `.ts` 文件
- 并尝试自动修复可修复问题

这说明 ESLint 默认并不是“无脑扫描整个磁盘所有文件”，而是：

**按命令和配置匹配要处理的文件。**

### 第二步：根据配置决定解析方式和规则集合

ESLint 会读取 `eslint.config.mjs`，再决定：

1. 对哪些文件用哪些规则
2. 用什么 parser
3. 这些文件处于什么语言环境
4. 是否需要类型信息

你当前项目里的配置是：

```js
export default tseslint.config(
  {
    ignores: ['eslint.config.mjs'],
  },
  eslint.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  eslintPluginPrettierRecommended,
  {
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.jest,
      },
      sourceType: 'commonjs',
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ['**/*.mjs'],
    extends: [tseslint.configs.disableTypeChecked],
    ...
  },
);
```

这表示：

- 普通 TS 文件启用推荐规则和带类型信息的规则
- `.mjs` 文件单独走另一套更轻的规则

### 第三步：parser 把源码转成 AST

例如某个 `.ts` 文件进入检查后，parser 会把源码解析成 AST。

如果源码本身连语法都不合法，例如少个括号、import 写错、对象字面量不完整，parser 这一步就会直接报错。

这类错误通常就是：

- Parsing error

所以有时候“ESLint 报错”其实并不是 rule 在报，而是**代码连语法树都建不出来**。

### 第四步：规则遍历 AST

一旦 AST 生成成功，ESLint 会把注册的规则跑起来。

每条规则通常只关注自己关心的节点类型。  
例如：

- 有的规则关心 `VariableDeclaration`
- 有的规则关心 `CallExpression`
- 有的规则关心 `AwaitExpression`
- 有的规则关心 `ImportDeclaration`

比如：

```ts
const x = 1;
```

`no-unused-vars` 这类规则就会在变量声明和变量引用之间建立关联，判断：

- 声明了没有
- 后面有没有真正用到

### 第五步：规则输出诊断结果

如果规则认为有问题，就会输出：

- error
- warning

并附带：

- 文件位置
- 规则名
- 问题描述

例如：

```txt
4:3  error  Insert `⏎`  prettier/prettier
```

这就说明：

1. 第 4 行第 3 列有问题
2. 问题级别是 error
3. 来源规则是 `prettier/prettier`

### 第六步：可修复规则可以自动改代码

如果规则支持 autofix，那么执行：

```bash
eslint --fix
```

时，ESLint 会把修复结果重新写回文件。

不过要注意：

**不是所有规则都能自动修。**

像：

- 格式问题
- 某些简单风格问题

通常可修。

但像：

- 业务逻辑错误
- 不明确的类型设计问题
- 可能引发语义变化的问题

很多规则不会自动改。

## 四、ESLint 是怎么判断“代码是否正确”的

这里要特别讲清楚“正确”这个词。

ESLint 检测的“正确”大致分 4 个层次。

### 1. 语法正确

这是最基础的一层。

例如：

```ts
const a = ;
```

这类代码 parser 连 AST 都建不出来，所以直接报语法解析错误。

### 2. 规则正确

即代码是否符合某些规范或最佳实践。

例如：

- 变量不能定义了不用
- 不允许某些危险写法
- import 顺序要符合规则
- Promise 不能随便丢着不处理

这类“正确”不是 JavaScript 引擎自己判断的，而是**团队或社区把经验沉淀成规则**。

### 3. 类型层面的正确

这一步是 `typescript-eslint` 的增强能力。

例如：

```ts
function callUser(input: any) {
  return doSomething(input.value);
}
```

如果启用了依赖类型信息的规则，它可以进一步分析：

- `input` 类型是否不安全
- `input.value` 是否存在不安全访问
- Promise 是否没处理

这类检查必须依赖 TypeScript 类型系统，不是仅靠语法就能知道的。

### 4. 格式层面的正确

这是 Prettier 参与进来的层次。  
虽然它不属于“业务正确”，但在工程工具链里，通常也被统一当成 lint 结果的一部分。

例如你之前看到的：

```txt
prettier/prettier
Insert `⏎`
```

本质上是在说：

**这份代码的排版不符合当前项目格式规则。**

## 五、作用过程的底层原理

如果更底层一点看，ESLint 的执行链路大致是：

1. **读取文件文本**
2. **根据文件名匹配配置**
3. **交给 parser 生成 AST**
4. **建立作用域和引用关系**
5. **运行规则访问器（visitor）**
6. **收集问题**
7. **必要时应用 autofix**
8. **输出结果**

这里有两个底层点很关键。

### 1. Visitor 模式

很多 ESLint 规则底层采用的是 visitor 模式。

简单理解就是：

- 规则先声明“我关心哪些节点”
- ESLint 遍历 AST 时，遇到这些节点就回调规则逻辑

例如伪代码可以理解成：

```js
create(context) {
  return {
    CallExpression(node) {
      // 检查函数调用是否符合规则
    },
    VariableDeclarator(node) {
      // 检查变量声明是否符合规则
    },
  };
}
```

所以规则不是“正则匹配整份文件”，而是**面向 AST 节点做结构化检查**。

### 2. 类型感知规则为什么更重

像 `@typescript-eslint/no-floating-promises` 这种规则，不能只看 AST。

它还需要问 TypeScript：

- 这个表达式的类型是什么？
- 它是不是 Promise？
- 这个 Promise 有没有被 `await`、`return` 或显式处理？

这就是为什么启用 type-checked 规则后：

- 检查更强
- 配置更复杂
- 性能开销更大
- 更容易和工具配置文件冲突

因为此时 ESLint 已不再只是“语法树检查器”，而是开始部分依赖 TS 编译器服务。

## 六、为什么 ESLint 有时能发现 bug，有时又不行

这是一个非常关键的认识。

ESLint 能发现很多问题，但它不能证明程序一定没 bug。

### ESLint 擅长发现的

1. 语法错误
2. 明显的危险写法
3. 违反团队规范的代码
4. 一部分类型不安全问题
5. 一部分 Promise / async 使用问题
6. 一部分无用代码和死代码线索

### ESLint 不擅长或做不到的

1. 业务逻辑是否符合真实需求
2. 复杂运行时状态下是否一定正确
3. 某些依赖真实输入、真实网络、真实数据库的错误
4. UI 交互结果是否符合预期
5. 算法结果是否真正正确

所以 ESLint 的价值不是“替代测试”，而是：

**把大量低层级、机械性、结构性问题提前在编码阶段拦下来。**

## 七、结合你当前项目，ESLint 是怎么工作的

在 `agent-server` 里，当前 ESLint 主要有这几个层次。

### 1. JS/TS 基础推荐规则

来自：

```js
eslint.configs.recommended
```

它会检查很多基础问题，例如：

- 未定义变量
- 某些明显错误模式
- 可疑语法

### 2. TypeScript 推荐规则

来自：

```js
...tseslint.configs.recommendedTypeChecked
```

这代表：

- 不只是支持 TypeScript 语法
- 还启用了依赖类型信息的推荐规则

所以像你前面遇到的 project service 问题，本质上就是这套“类型感知 lint”链路引出的。

### 3. Prettier 规则接入

来自：

```js
eslintPluginPrettierRecommended
```

它会把 Prettier 格式问题也作为 ESLint 结果输出。

所以你执行 `eslint` 时，有时看到的并不是“语义错误”，而只是：

- 结尾缺换行
- 缩进不一致
- 排版不符合 Prettier

### 4. 项目自定义规则

你当前还额外加了：

```js
rules: {
  '@typescript-eslint/no-explicit-any': 'off',
  '@typescript-eslint/no-floating-promises': 'warn',
  '@typescript-eslint/no-unsafe-argument': 'warn'
}
```

这表示你们项目额外关心：

- Promise 处理是否规范
- 参数传递是否不安全

同时对 `any` 较宽松。

### 5. `.mjs` 配置文件走单独规则

你当前又专门给 `.mjs` 做了特殊处理：

```js
{
  files: ['**/*.mjs'],
  extends: [tseslint.configs.disableTypeChecked],
  ...
}
```

这说明你已经在实践一个很重要的原则：

**不同类型的文件，应该走不同强度的 lint 策略。**

业务 TS 源码需要更强的类型检查。  
工具配置文件只需要更轻、更适配的规则。

## 八、扩展知识与注意点

### 1. ESLint 不是 TypeScript 编译器

虽然它可以利用 TS 类型信息，但它本身不等于 `tsc`。  
`tsc` 更关注：

- 类型系统是否成立
- 编译是否能通过

ESLint 更关注：

- 规则是否违反
- 写法是否规范
- 是否存在可疑模式

两者有交集，但不是同一件事。

### 2. ESLint 规则很多都带“主观性”

有些规则更接近“团队规范”，并不存在绝对正确答案。  
例如：

- 是否允许 `any`
- 是否强制某种 import 排序
- 是否要求特定风格

所以 ESLint 一部分是在检查“错误”，另一部分是在执行“约定”。

### 3. Type-aware lint 越强，越要注意配置边界

当你启用：

- `projectService: true`
- `recommendedTypeChecked`

就意味着：

1. 更强的检查能力
2. 更高的配置复杂度
3. 对工具文件、配置文件、非 TS 源码更敏感

所以大型项目里常常需要为：

- 源码文件
- 测试文件
- 配置文件
- 脚本文件

分别配置 lint 策略。

### 4. `eslint --fix` 只是“在规则允许下自动修”

它不是 AI，也不是代码重构引擎。  
它只能对规则明确支持 autofix 的问题做自动修改。

### 5. ESLint 最有价值的时机是“写代码时”和“提交前”

它的最大价值，不是在 CI 最后报你一堆错，而是：

1. 编辑器里实时提示
2. 提交前通过 `lint-staged` 自动拦住
3. CI 再做兜底

这样问题会尽量在最早阶段暴露。

## 九、一句话总结

ESLint 检测“代码是否正确”的方式，不是运行代码看结果，而是：

**把代码解析成 AST，再结合作用域分析、规则系统以及可选的 TypeScript 类型信息，对代码结构、语义风险、约定规范和格式问题进行静态检查。**

---

# JavaScript 原生网络请求接口详解

## 一、先澄清几个容易混淆的概念

在讨论 JS 网络请求时，最容易混淆的是下面三组概念：

1. **网络请求接口 / API**
2. **HTTP 请求方法**
3. **REST / RESTful**

它们不是一回事。

### 1. 网络请求接口 / API

这是“你在代码里调用的能力入口”。

例如：

- `fetch()`
- `XMLHttpRequest`
- `http.request()`
- `WebSocket`
- `EventSource`

这些都可以叫“网络通信接口”或“网络请求 API”。

### 2. HTTP 请求方法

这是 HTTP 协议层面的动作类型。

例如：

- `GET`
- `POST`
- `PUT`
- `PATCH`
- `DELETE`
- `HEAD`
- `OPTIONS`

这些不是 JS 函数，而是 HTTP 报文里的方法字段。

例如：

```ts
fetch('/api/users', { method: 'GET' })
```

这里：

- `fetch` 是 JS 提供的网络请求接口
- `GET` 是 HTTP 请求方法

### 3. REST / RESTful

REST 是一种“接口设计风格”或“架构风格”，不是 JS 内置函数。

例如下面这种接口风格通常被叫 RESTful：

- `GET /users`
- `GET /users/:id`
- `POST /users`
- `PATCH /users/:id`
- `DELETE /users/:id`

所以：

- `fetch` 不是 RESTful 方法
- `http.request` 也不是 RESTful 方法
- 它们只是“发 HTTP 请求的工具”
- 你既可以用它们请求 RESTful API，也可以请求非 RESTful API

## 二、JS 中常见的原生网络请求接口有哪些

如果从“现代 JavaScript 开发”角度看，原生网络接口主要分为两大运行环境：

1. 浏览器环境
2. Node.js 环境

## 三、浏览器里的原生网络请求接口

### 1. `fetch()`

这是现代前端最主流的原生 HTTP 请求接口。

特点：

- 基于 Promise
- 写法简洁
- 适合请求 REST API、上传 JSON、读取文本/二进制等
- 浏览器原生支持，现代 Node.js 也支持

示例：

```ts
const response = await fetch('/api/users', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ name: 'Tom' }),
});

const data = await response.json();
```

#### 它能做什么

- 发 `GET/POST/PUT/PATCH/DELETE` 等 HTTP 请求
- 发送请求头
- 发送 JSON / 文本 / `FormData` / 二进制
- 读取响应头、状态码、响应体
- 搭配 `AbortController` 取消请求

#### 它的核心对象

- `Request`
- `Response`
- `Headers`
- `AbortController`
- `AbortSignal`

#### 常见 `fetch` 参数

- `method`：请求方法
- `headers`：请求头
- `body`：请求体
- `signal`：中止信号
- `mode`：请求模式
- `credentials`：凭据携带策略
- `cache`：缓存策略
- `redirect`：重定向处理策略
- `referrer`：引用来源
- `integrity`：完整性校验
- `keepalive`：页面卸载后保持请求发送

其中日常最常见的是：

- `method`：请求方法
- `headers`：请求头
- `body`：请求体
- `signal`：中止信号
- `credentials`：凭据携带策略

#### 常见 `Response` 属性 / 方法

- `ok`：是否处于 2xx 成功状态
- `status`：响应状态码
- `statusText`：状态描述文本
- `headers`：响应头集合
- `url`：最终响应 URL
- `json()`：按 JSON 解析响应体
- `text()`：按文本读取响应体
- `blob()`：按 Blob 二进制对象读取响应体
- `arrayBuffer()`：按二进制缓冲区读取响应体
- `formData()`：按表单数据结构读取响应体

### 2. `XMLHttpRequest`

这是更早期的浏览器原生 HTTP 请求接口，简称 `XHR`。

它比 `fetch` 更老，典型写法是：

```ts
const xhr = new XMLHttpRequest();
xhr.open('GET', '/api/users');
xhr.onload = () => {
  console.log(xhr.responseText);
};
xhr.send();
```

#### 特点

- 老牌浏览器接口
- 基于事件回调，不是基于 Promise
- 写法更啰嗦
- 仍然能用，但现代项目通常更偏向 `fetch`

#### 它现在还有没有价值

有，但场景变少了。

主要在这些场景还可能见到：

- 维护老项目
- 某些上传进度监听场景
- 历史封装库底层依赖 XHR

### 3. `WebSocket`

这是浏览器原生的“长连接双向通信”接口。

它不是传统的 HTTP 请求接口，但属于原生网络通信接口。

特点：

- 客户端和服务端都可以主动发消息
- 适合即时聊天、实时协作、推送、交易行情等
- 建立连接时会先通过 HTTP Upgrade 升级协议

示例：

```ts
const ws = new WebSocket('ws://localhost:3000/ws');
ws.onmessage = (event) => {
  console.log(event.data);
};
ws.send('hello');
```

### 4. `EventSource`

这是浏览器原生的 SSE（Server-Sent Events）接口。

特点：

- 服务端单向推送到客户端
- 基于 HTTP
- 比 WebSocket 更轻量
- 适合日志流、任务进度、通知流

示例：

```ts
const source = new EventSource('/api/agent/runs/123/stream');
source.addEventListener('run_started', (event) => {
  console.log(event);
});
```

你当前项目里的 Agent 进度流就更接近这种模式。

### 5. `navigator.sendBeacon()`

这是浏览器原生的“轻量后台上报”接口。

适合：

- 页面关闭前上报埋点
- 统计日志
- 简单监控事件

它不是通用 HTTP 客户端，不适合复杂业务请求。

### 6. `<img>`、`<script>`、`<link>` 等资源加载

严格来说，这些不是“程序员主动调用的请求 API”，但它们底层也会触发网络请求。

例如：

- `<img src="...">`
- `<script src="...">`
- `<link href="...">`

这是浏览器自动发起的资源请求机制。

历史上 JSONP 就是利用 `<script>` 标签跨域加载的技巧。

## 四、Node.js 里的原生网络请求接口

Node.js 没有浏览器 DOM，但它也有自己的原生网络通信能力。

### 1. `fetch()`

现代 Node.js 已经内置了标准 `fetch`。

这意味着在新版本 Node 里，你通常可以直接这样写：

```ts
const response = await fetch('http://localhost:11434/api/chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ foo: 'bar' }),
});
```

这也是你当前 `OllamaProvider` 使用的方式。

#### 为什么现在很多 Node 项目也改用 `fetch`

- 语法统一，前后端心智一致
- 标准化程度高
- 不必再额外安装老牌 HTTP 请求库才能完成简单调用

### 2. `http.request()`

这是 Node.js 很经典的原生 HTTP 客户端接口，来自：

```ts
import * as http from 'node:http';
```

示例：

```ts
import * as http from 'node:http';

const req = http.request(
  {
    hostname: 'example.com',
    port: 80,
    path: '/api/users',
    method: 'GET',
  },
  (res) => {
    let data = '';
    res.on('data', (chunk) => {
      data += chunk;
    });
    res.on('end', () => {
      console.log(data);
    });
  },
);

req.on('error', console.error);
req.end();
```

#### 它的特点

- 更底层
- 更接近 Node 流和 socket 模型
- 代码更啰嗦
- 需要自己处理 chunk、end、error
- 更适合需要精细控制的底层场景

#### 它是不是 RESTful 风格请求方法

不是。

它只是一个“发送 HTTP 请求的底层 API”。  
你当然可以用它去调用 RESTful 接口，但它本身不等于 REST。

### 3. `https.request()`

与 `http.request()` 类似，只不过用于 HTTPS。

来自：

```ts
import * as https from 'node:https';
```

如果你需要：

- TLS/HTTPS 请求
- 证书控制
- 更底层的安全通信配置

这个 API 仍然有价值。

### 4. `http.get()` / `https.get()`

这是 `request` 的简化封装。

适合简单 GET 请求。

例如：

```ts
import * as https from 'node:https';

https.get('https://example.com', (res) => {
  // ...
});
```

它本质仍然是底层 HTTP 客户端接口的一种简化调用方式。

### 5. `http2`

Node 还提供 `http2` 模块。

它用于：

- HTTP/2 协议通信
- 多路复用
- 头部压缩

这个接口更偏协议级能力，业务项目里不会像 `fetch` 那么常用。

### 6. 更底层的 `net` / `tls` / `dgram`

如果再往下走，就不是“HTTP 请求接口”了，而是更底层的网络接口：

- `net`：TCP
- `tls`：TLS 加密 TCP
- `dgram`：UDP

这些都属于 Node 原生网络能力，但它们已经不是“请求 REST API 的接口”，而是更底层的网络编程接口。

## 五、`fetch` 和 `http.request` 都是内置的 RESTful 风格请求方法吗

严格来说，不是。

更准确的说法应该是：

- `fetch` 是 JS/浏览器/现代 Node 提供的原生 HTTP 请求接口
- `http.request` 是 Node 提供的原生 HTTP 客户端底层接口
- RESTful 是接口设计风格，不是这两个 API 自身的属性

### 正确理解方式

你可以这样类比：

- `fetch` / `http.request` = 交通工具
- RESTful API = 你要去的道路规则

交通工具不是“RESTful”，它只是用来访问某个接口。

如果目标接口遵循 REST 设计，你就是在“用 `fetch` 调 RESTful API”。
如果目标接口不是 REST，而是 RPC 风格、GraphQL、SSE、流式输出、传统表单接口，那你照样也可以用 `fetch` 去访问。

## 六、除了 `fetch` 和 `http.request`，还有哪些“内置请求方法”

这里要分两种理解。

### 1. 如果你问的是“原生网络接口”

常见有：

- 浏览器：`fetch`、`XMLHttpRequest`、`WebSocket`、`EventSource`、`navigator.sendBeacon`
- Node：`fetch`、`http.request`、`https.request`、`http.get`、`https.get`、`http2`

### 2. 如果你问的是“HTTP 请求方法”

常见内置的协议方法有：

- `GET`
- `POST`
- `PUT`
- `PATCH`
- `DELETE`
- `HEAD`
- `OPTIONS`

这些不是 JS API，而是 HTTP 协议标准的一部分。

## 七、这些接口本质上在做什么

它们本质上都在做一件事：

> 按某种网络协议，把本地程序的数据发送给远端，再把远端响应读回来。

如果是 HTTP 系列接口，大体流程可以理解成：

1. 构造 URL、方法、请求头、请求体
2. 建立连接
3. 把请求报文发给服务端
4. 服务端处理后返回响应报文
5. 客户端读取状态码、响应头、响应体
6. 把原始字节流转换成 JSON / 文本 / 二进制数据

`fetch` 和 `http.request` 的区别，不在于“能不能发 HTTP 请求”，而在于：

- 抽象层级不同
- 易用性不同
- 对流、超时、重试、连接控制的掌控粒度不同

## 八、`fetch` 和 `http.request` 的底层区别

### `fetch`

更高层、更现代。

特点：

- Promise 风格
- API 更统一
- 与浏览器语义一致
- 更适合大多数业务请求

开发者通常更关注：

- 发什么 URL
- 用什么 method
- body 是什么
- 怎么解析 response

### `http.request`

更底层、更 Node 风格。

特点：

- 面向流和事件
- 更接近 socket / 协议层
- 需要自己处理数据块拼接
- 适合细粒度控制

开发者通常还要额外处理：

- `data` 事件
- `end` 事件
- `error` 事件
- `req.end()`

## 九、业界常用的请求方式是原生能力还是第三方工具

答案是：

> 两者都很多，但趋势正在变化。

## 十、前端业界常见做法

### 1. 现代前端项目

现在越来越多项目直接使用原生 `fetch`。

原因：

- 浏览器原生支持
- 标准化
- 无额外依赖
- 搭配封装后已经足够实用

很多团队会在 `fetch` 外层自己封一个轻量请求器，例如统一处理：

- base URL
- token 注入
- 超时
- 错误码处理
- 自动解析 JSON

### 2. 为什么很多前端项目仍然使用 `axios`

`axios` 很长时间都是前端最流行的 HTTP 库之一。

它流行的原因包括：

- API 友好
- 请求/响应拦截器好用
- 自动 JSON 处理体验较好
- 历史兼容性强
- 团队积累多

所以当前业界并不是“全部切到原生 `fetch`”。

更真实的情况是：

- 新项目：很多直接 `fetch`
- 中大型前端：`fetch` 或 `axios` 都很常见
- 老项目：`axios` 仍然大量存在

## 十一、Node.js 后端业界常见做法

### 1. 过去

Node 里曾经大量使用第三方 HTTP 客户端，例如：

- `axios`
- `request`（已废弃）
- `superagent`
- `got`
- `node-fetch`

### 2. 现在

现在现代 Node 项目越来越常见的选择是：

- 简单请求：原生 `fetch`
- 复杂请求：`axios`、`got` 或更专业的封装

### 3. 为什么后端有时仍偏爱第三方工具

因为很多后端场景需要更完整的工程能力，例如：

- 超时控制
- 自动重试
- 代理
- 连接池
- 拦截器
- 更细的流处理
- 更完善的错误对象
- 更方便的上传下载能力

原生能力能做，但第三方库往往“开箱更顺手”。

## 十二、常见第三方请求工具有哪些

### 浏览器 / 通用 TS 项目

- `axios`
- `ky`
- `superagent`

### Node.js 后端

- `axios`
- `got`
- `superagent`
- `undici`

### 特别说明：`undici`

`undici` 是 Node 官方生态里非常重要的 HTTP 客户端实现。  
现代 Node 的原生 `fetch` 能力本身就与它关系很深。

所以很多时候你以为自己“只是用原生 fetch”，底层实现其实已经和现代 Node HTTP 客户端生态紧密相关。