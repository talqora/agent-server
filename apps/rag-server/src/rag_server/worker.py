"""worker 进程入口:无 HTTP,只消费 Pulsar 队列(rag-runs)。

与 Node 版对齐(apps/node-server/src/main.worker.ts):
- 与 HTTP 进程共享同一份核心上下文(DB/Redis/Milvus/LLM/RunEngine);
- 优雅退出:收到 SIGTERM/SIGINT → 停止拉新消息 → 处理完手头消息 → 关闭退出。
"""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from agent_core.logging import setup_logging
from agent_core.queue import RunJobConsumer

from rag_server.context import build_core, close_core
from rag_server.modules.runs.processor import RunProcessor
from rag_server.settings import get_settings

logger = logging.getLogger("rag_server.worker")


def _log_consume_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("消费循环异常退出", exc_info=exc)


async def _run() -> None:
    settings = get_settings()
    setup_logging("rag-worker", settings.log_level)

    ctx = await build_core(settings)
    processor = RunProcessor(ctx)
    consumer = RunJobConsumer(
        settings.pulsar_url,
        settings.pulsar_topic,
        settings.pulsar_subscription,
        processor.process,
    )
    await consumer.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    consume_task = asyncio.create_task(consumer.run_forever())
    # 消费循环异常必须可见:否则任务静默死亡,worker"假活"不再消费(踩过)
    consume_task.add_done_callback(_log_consume_failure)
    await stop_event.wait()
    logger.info("收到停止信号,优雅退出(停止拉新消息,处理完手头消息)…")

    await consumer.stop()
    await consume_task
    await consumer.close()
    await close_core(ctx)
    logger.info("worker 已退出")


def run() -> None:
    """console script 入口:rag-worker。"""
    asyncio.run(_run())
