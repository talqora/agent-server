"""健康检查基座:并行探活各依赖,返回 {status, details}。

与 Node 版对齐(/api/health):任一项 down → 整体 degraded,但仍 200 返回 details。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


async def check_components(
    probes: dict[str, Callable[[], Awaitable[Any]]],
) -> dict[str, Any]:
    """并行执行探活。probes: 组件名 → 异步探活函数(正常返回即 up,抛异常即 down)。"""
    names = list(probes)
    results = await asyncio.gather(*(probes[name]() for name in names), return_exceptions=True)

    details: dict[str, dict[str, Any]] = {}
    for name, result in zip(names, results, strict=True):
        if isinstance(result, BaseException):
            details[name] = {"status": "down", "error": str(result)}
        else:
            details[name] = {"status": "up"}

    all_up = all(d["status"] == "up" for d in details.values())
    return {"status": "ok" if all_up else "degraded", "details": details}
