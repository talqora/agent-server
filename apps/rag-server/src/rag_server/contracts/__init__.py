"""契约层:proto 生成类型(betterproto2 + pydantic dataclass)的消费入口。

设计(见 docs/架构设计/03 §6.4 与迁移路线图 M0):
- ``contracts/gen/`` 是 proto 的生成物(**禁止手改**,由 buf + betterproto2 生成);
- 本模块在导入时给全部生成类注入 **camelCase alias**
  (``alias_generator=to_camel`` + ``populate_by_name=True``),使生成类型可直接作为
  FastAPI 的请求模型:请求接受 camelCase、类型错误 422、OpenAPI 自动生成;
- **响应序列化**走 betterproto2 的 ``to_dict()``(proto3-JSON 权威:lowerCamelCase、
  google.protobuf.Struct 正确展开为普通对象),由路由经 ``wire()`` 输出;
- 所有业务类型都从这里取——不手写与 proto 平行的 DTO(Node 版偏离的纠正)。
"""

from __future__ import annotations

from typing import Any

import betterproto2
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel
from pydantic.dataclasses import rebuild_dataclass

from rag_server.contracts.gen.ourchat.agent.v1 import (
    AgentConversation,
    AgentDocument,
    AgentMessage,
    AgentRun,
    AgentRunDetail,
    AgentTaskResp,
    AgentTaskSession,
    AgentTaskSessionDetail,
    AgentUser,
    AuthResp,
    ChatDoneEvent,
    ChatTokenEvent,
    Citation,
    CreateConversationReq,
    CreateTaskReq,
    CreateTaskSessionReq,
    LoginReq,
    RegisterReq,
    RunEvent,
    RunEventRow,
    RunIdResp,
    RunSnapshotResp,
    SendMessageReq,
    UploadDocResp,
)

__all__ = [
    "AgentConversation",
    "AgentDocument",
    "AgentMessage",
    "AgentRun",
    "AgentRunDetail",
    "AgentTaskResp",
    "AgentTaskSession",
    "AgentTaskSessionDetail",
    "AgentUser",
    "AuthResp",
    "ChatDoneEvent",
    "ChatTokenEvent",
    "Citation",
    "CreateConversationReq",
    "CreateTaskReq",
    "CreateTaskSessionReq",
    "LoginReq",
    "RegisterReq",
    "RunEvent",
    "RunEventRow",
    "RunIdResp",
    "RunSnapshotResp",
    "SendMessageReq",
    "UploadDocResp",
    "apply_camel_aliases",
    "wire",
]


def apply_camel_aliases() -> None:
    """给全部生成消息类注入 camelCase alias(幂等)。

    必须在创建 FastAPI app 之前执行(导入本模块即已执行)。
    说明:生成类是 pydantic dataclass;通过 force rebuild 重算校验/序列化 schema,
    使 ``displayName`` 等 camelCase 入参可被解析、OpenAPI 展示 camelCase 字段。
    """
    import rag_server.contracts.gen.ourchat.agent.v1 as gen_v1

    for name in dir(gen_v1):
        cls = getattr(gen_v1, name)
        if isinstance(cls, type) and issubclass(cls, betterproto2.Message):
            cls.__pydantic_config__ = ConfigDict(  # type: ignore[attr-defined]
                alias_generator=to_camel,
                populate_by_name=True,
                # 对齐 Node 版 ValidationPipe(whitelist 丢弃未声明字段,不报错)
                extra="ignore",
            )
            rebuild_dataclass(cls, force=True)  # type: ignore[arg-type]


def wire(msg: betterproto2.Message) -> dict[str, Any]:
    """契约消息 → 线格式 dict(proto3-JSON:camelCase、Struct 展开、空值省略)。"""
    return msg.to_dict()


# 导入即生效:任何使用契约类型的入口(HTTP/worker/测试)都得到一致的 camelCase 行为。
apply_camel_aliases()
