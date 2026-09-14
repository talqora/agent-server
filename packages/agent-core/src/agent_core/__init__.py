"""agent-core —— agent-server 多服务的共享基座。

职责边界(多服务纪律,见 docs/架构设计/03):
- **只放多服务公共的机制**,不放任何服务自己的领域逻辑/表结构/工具/prompt;
- 不 import 任何服务代码;服务通过注入(Protocol/回调/模型)使用本库;
- 服务接入点:settings / logging / db / redis / events / auth / federated /
  run_engine / queue / llm / vector / health。
"""

from agent_core import (
    auth,
    db,
    events,
    federated,
    health,
    llm,
    logging,
    queue,
    redis,
    run_engine,
    settings,
    vector,
)

__all__ = [
    "auth",
    "db",
    "events",
    "federated",
    "health",
    "llm",
    "logging",
    "queue",
    "redis",
    "run_engine",
    "settings",
    "vector",
]
