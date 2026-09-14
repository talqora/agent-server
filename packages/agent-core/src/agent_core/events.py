"""运行事件广播:Redis pub/sub 背板(多 HTTP 副本跨副本收事件)。

纪律(见 docs/架构设计/02-实时进度与任务队列架构评审):
- 广播是 **best-effort**:丢了不影响正确性——正确性由 PG 事件溯源 + SSE 断线补发兜底;
- 频道命名带服务前缀 ``<prefix>:run:<runId>``,多服务不串台;
- 订阅必须用独立连接(RedisClient.duplicate)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from agent_core.redis import RedisClient

if TYPE_CHECKING:
    from redis.asyncio.client import PubSub


def run_channel(prefix: str, run_id: str) -> str:
    """某个 run 的事件频道名。"""
    return f"{prefix}:run:{run_id}"


class RunSubscription:
    """一次 run 的订阅句柄:异步迭代事件 dict;用完必须 close()。"""

    def __init__(self, pubsub: PubSub, channel: str) -> None:
        self._pubsub = pubsub
        self._channel = channel
        self._closed = False

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """持续产出该 run 的事件(JSON → dict)。close() 后迭代自然结束。"""
        while not self._closed:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue
            data = message.get("data")
            if isinstance(data, str):
                yield json.loads(data)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._pubsub.unsubscribe(self._channel)
        finally:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]


class EventBus:
    """运行事件广播器(worker 发 / HTTP 进程收)。"""

    def __init__(self, redis: RedisClient, channel_prefix: str) -> None:
        self._redis = redis
        self._prefix = channel_prefix

    async def publish_run_event(self, run_id: str, payload: dict[str, Any]) -> None:
        """发布一条运行事件(JSON 序列化,中文不转义)。"""
        await self._redis.client.publish(
            run_channel(self._prefix, run_id), json.dumps(payload, ensure_ascii=False)
        )

    async def subscribe_run(self, run_id: str) -> RunSubscription:
        """订阅某个 run 的实时事件(独立连接)。"""
        pubsub = (await self._redis.duplicate()).pubsub()
        channel = run_channel(self._prefix, run_id)
        await pubsub.subscribe(channel)
        return RunSubscription(pubsub, channel)
