# 05 · 契约生成与 FastAPI 整合方案（Python 侧）

> 决策回顾（01 §6.4）：**所有业务类型从统一 proto 生成并使用**——Node 版只有 `Citation` 一处消费
> 生成类型、对外形状靠手写 DTO，属于开发偏离；重写纠正它。
> 本文记录：工具选型（spike 实测）、生成链路、FastAPI 三层整合方案、已知边界与使用纪律。
> 所有结论有 spike 实测证据（见 §6），不是纸面推演。

---

## 1. 工具选型：betterproto2 0.10.0（实测后定）

| 候选 | 结论 | 理由（实测） |
|---|---|---|
| **betterproto2 0.10.0** | ✅ 选它 | 活跃维护（2026 年仍在发版）；`pydantic_dataclasses` 生成 **pydantic dataclass**（含 int32 边界/字符串校验器）；`to_dict()` 默认 **camelCase** 且 `Struct` 正确展开为普通对象；`from_dict` 对未知字段严格（兜住映射错误） |
| betterproto 2.0.0b7（原版） | ❌ | 2023 年的 beta，依赖链有 `SyntaxWarning`；`Struct` 经 dict 直传时序列化丢字段（实测踩到） |
| 官方 protobuf 插件（`_pb2.py`） | ❌ | 生成的消息类与 FastAPI/pydantic 有阻抗；JSON 需 `json_format` 手动桥接，OpenAPI 无法自动生成 |
| 手写 pydantic 模型 | ❌ | 正是要纠正的偏离（契约漂移风险） |

版本钉死（两处必须一致）：
- 运行时：`apps/rag-server/pyproject.toml` → `betterproto2==0.10.0`；
- 生成器：`buf.gen.yaml` 本地插件 → `uv tool install betterproto2_compiler==0.10.0`（CI 在 `proto.yml` 里同款安装）。

---

## 2. 生成链路

```
proto/ourchat/agent/v1/agent.proto（权威）
   ├─ ts-proto → apps/node-server/src/contracts/gen        （Node 对照,保留）
   ├─ ts-proto → packages/agent-contracts/src/gen          （web 消费的 npm 包）
   └─ betterproto2 → apps/rag-server/src/rag_server/contracts/gen   ← Python(本方案)
```

- `buf.gen.yaml` 第三个目标：`local: protoc-gen-python_betterproto2` + `opt: [pydantic_dataclasses]`；
- 生成物**禁止手改**；`proto.yml` freshness 校验已纳入该路径（与 TS 两份同规则）；
- proto 变更流程不变：改 proto → `buf generate` → 提交（web 包另需 bump version 触发发布）。

---

## 3. FastAPI 三层整合方案

### 3.1 请求：生成类型直接作 body 模型 + camelCase alias 注入

生成类是 pydantic dataclass，但**默认字段名是 snake_case**（FastAPI 只认 `display_name`，不认 `displayName`）。
在 `rag_server/contracts/__init__.py` 导入时统一注入：

```python
cls.__pydantic_config__ = ConfigDict(
    alias_generator=to_camel, populate_by_name=True, extra="ignore"
)
rebuild_dataclass(cls, force=True)  # force 必需:重建校验/序列化 schema
```

效果（实测）：请求收 camelCase（也兼容 snake_case）；类型错误 → 422；未声明字段丢弃（对齐 Node 的
`whitelist: true`）；OpenAPI 展示 camelCase 字段名。

### 3.2 响应：`to_dict()` 输出（proto3-JSON 权威）

FastAPI 的 `response_model` 序列化走 pydantic——对**嵌套生成类型/Struct 字段**会输出 snake_case 与
`{"fields": {...}}` 的错误形状（实测）。因此响应统一：

```python
msg = AgentDocument.from_dict({...camelCase 显式映射...})   # ORM 行 → 契约消息(过滤+校验)
return JSONResponse(content=wire(msg))                     # wire() = msg.to_dict()
```

- 路由仍声明 `response_model=<生成类型>`（**只用于 OpenAPI 文档**；返回 Response 时 FastAPI 跳过其序列化）；
- `from_dict` 显式白名单映射：ORM 的内部字段（`user_id`/`storage_path` 等）不会漏出；
- 嵌套与 `Struct`（事件 payload）由 betterproto2 正确展开（实测：`payload` 为普通对象）。

### 3.3 SSE：帧手写，data 用 `to_dict()`

- Run 流：`id: <sequenceNo>`、`event: <eventType>`、`data: 整条 run_event 行（camelCase）`；
- 对话流：`event: token|done|error`，data 自带 `type` 字段（与 web 端解析逻辑逐字对齐）；
- 断线补发（`Last-Event-ID`）与 watermark 去重逻辑见 02 文档，与序列化层无关。

---

## 4. 已知边界（诚实清单）

| 边界 | 说明 | 对策 |
|---|---|---|
| proto3 表达不了值级约束 | 长度/范围/非空（如 query 非空、topK 1–20） | 业务层显式校验（`BadRequestError`）；未来可选 `buf validate` |
| 生成类不可加业务方法 | 生成物禁止手改 | 领域逻辑放服务层；需要时用 `from_dict` 构造后传值 |
| 生成物内的 pydantic 弃用警告 | betterproto2 生成代码用旧式 `model_validator` | 测试过滤该警告；上游升级后消除 |

## 5. 使用纪律（code review 检查项）

1. **禁止手写与 proto 平行的 DTO**——请求/响应/SSE 载荷类型一律从 `rag_server.contracts` 取；
2. ORM 行对象是内部类型：**出口转换一次**为契约消息（不许 ORM 直出，也不许中间套三层）；
3. 响应必须经 `wire()`（`to_dict`）输出，不允许把生成对象直接交给 FastAPI 序列化；
4. 契约变更只改 proto + 重新生成，不改生成物。

## 6. spike 实测证据（摘要）

| 验证项 | 结果 |
|---|---|
| pydantic 校验生效 | 错类型 → `ValidationError`（含 int32 边界） |
| `to_dict()` casing | 默认 camelCase；`Casing.SNAKE` 可选 |
| `from_dict` | camelCase/snake_case 都收；未知字段抛 `KeyError`（严格） |
| Struct 往返 | `payload={"step": "parsing"}` → `to_dict()` 输出普通对象 ✅ |
| alias 注入后 FastAPI | camelCase 请求解析 ✅ / snake_case 兼容 ✅ / 422 ✅ / OpenAPI camelCase ✅ |
| 响应绕过序列化 | `JSONResponse(to_dict())` 输出与 Node 线格式逐字段一致（含 `errorMsg: null` 语义省略） |
| E2E（真实全栈） | `tools/e2e_test.py` 26/26 通过（含事件行形状、citations、工具链） |
