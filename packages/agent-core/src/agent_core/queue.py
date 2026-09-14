"""任务队列(Pulsar)封装:生产者(HTTP 进程)+ 消费者(worker 进程)。

与 Node 版对齐(apps/node-server/src/shared/queue):
- 载荷只带定位信息 ``{runId, userId, kind}``,业务状态以 DB 的 Run 为准;
- kind 对齐 BullMQ 时代的 job.name(ingestion / agent / demo);
- 消费语义对齐 BullMQ:Shared 订阅(多 worker 竞争消费,一条消息只投一个副本)、
  处理成功 ack、失败 nack 重投(至少一次;幂等由业务保证)、优雅退出(停拉新消息,处理完手头再关)。

pulsar-client 是同步客户端:所有阻塞调用统一走 asyncio.to_thread,不阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pulsar

logger = logging.getLogger("agent_core.queue")

RUN_JOB_KIND_INGESTION = "ingestion"
RUN_JOB_KIND_AGENT = "agent"
RUN_JOB_KIND_DEMO = "demo"


@dataclass(frozen=True)
class RunJob:
    """队列载荷:只带定位信息(内容回查 DB)。"""

    run_id: str
    user_id: int
    kind: str  # ingestion / agent / demo

    def to_bytes(self) -> bytes:
        # 键名与 Node 版 RunJobData 一致(camelCase),便于跨端排查
        return json.dumps({"runId": self.run_id, "userId": self.user_id, "kind": self.kind}).encode(
            "utf-8"
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> RunJob:
        obj = json.loads(data.decode("utf-8"))
        return cls(run_id=str(obj["runId"]), user_id=int(obj["userId"]), kind=str(obj["kind"]))


class RunJobProducer:
    """生产者(HTTP 进程):入队即返回,不等任务跑完。"""

    def __init__(self, service_url: str, topic: str) -> None:
        self._service_url = service_url
        self._topic = topic
        self._client: pulsar.Client | None = None
        self._producer: pulsar.Producer | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        def _create() -> tuple[pulsar.Client, pulsar.Producer]:
            client = pulsar.Client(self._service_url)
            producer = client.create_producer(self._topic)
            return client, producer

        self._client, self._producer = await asyncio.to_thread(_create)
        logger.info("Pulsar producer 已启动 topic=%s", self._topic)

    async def send(self, job: RunJob) -> None:
        if self._producer is None:
            async with self._lock:
                if self._producer is None:
                    await self.start()
        assert self._producer is not None
        await asyncio.to_thread(self._producer.send, job.to_bytes())

    async def close(self) -> None:
        def _close() -> None:
            if self._producer is not None:
                self._producer.close()
            if self._client is not None:
                self._client.close()

        await asyncio.to_thread(_close)
        self._producer = None
        self._client = None


class RunJobConsumer:
    """消费者(worker 进程):Shared 订阅竞争消费 + ack/nack + 优雅退出。"""

    def __init__(
        self,
        service_url: str,
        topic: str,
        subscription: str,
        handler: Callable[[RunJob], Awaitable[None]],
        *,
        receive_timeout_ms: int = 1000,
    ) -> None:
        self._service_url = service_url
        self._topic = topic
        self._subscription = subscription
        self._handler = handler
        self._receive_timeout_ms = receive_timeout_ms
        self._client: pulsar.Client | None = None
        self._consumer: pulsar.Consumer | None = None
        self._stopping = False

    async def start(self) -> None:
        def _create() -> tuple[pulsar.Client, pulsar.Consumer]:
            client = pulsar.Client(self._service_url)
            consumer = client.subscribe(
                self._topic,
                subscription_name=self._subscription,
                # Shared:多副本竞争消费(一条消息只投一个消费者),对齐 BullMQ Worker
                consumer_type=pulsar.ConsumerType.Shared,
            )
            return client, consumer

        self._client, self._consumer = await asyncio.to_thread(_create)
        logger.info(
            "Pulsar consumer 已启动 topic=%s subscription=%s", self._topic, self._subscription
        )

    async def run_forever(self) -> None:
        """消费循环:成功 ack;失败 nack(重投)+ 日志;stop() 后退出。"""
        if self._consumer is None:
            await self.start()
        assert self._consumer is not None

        while not self._stopping:
            try:
                msg = await asyncio.to_thread(self._consumer.receive, self._receive_timeout_ms)
            except pulsar.Timeout:
                # 空轮询(超时无消息)是常态:回到循环顶部检查停止标记
                continue
            except Exception:
                logger.exception("接收消息失败,1s 后重试")
                await asyncio.sleep(1.0)
                continue
            if msg is None:
                continue
            job: RunJob | None = None
            try:
                job = RunJob.from_bytes(msg.data())
                logger.info("开始处理 run=%s (kind=%s)", job.run_id, job.kind)
                await self._handler(job)
                await asyncio.to_thread(self._consumer.acknowledge, msg)
                logger.info("完成 run=%s", job.run_id)
            except Exception:
                logger.exception("处理失败,消息将重投 run=%s", job.run_id if job else "?")
                await asyncio.to_thread(self._consumer.negative_acknowledge, msg)

    async def stop(self) -> None:
        """优雅退出:置停止标记(循环处理完当前消息后退出)。"""
        self._stopping = True

    async def close(self) -> None:
        def _close() -> None:
            if self._consumer is not None:
                self._consumer.close()
            if self._client is not None:
                self._client.close()

        await asyncio.to_thread(_close)
        self._consumer = None
        self._client = None
