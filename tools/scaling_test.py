"""独立扩缩容验证(对齐 docs/架构设计/03 §6.2)。

验证项:
  1. **跨副本 SSE**:run 在 HTTP 副本 A 提交、SSE 连到副本 B → 事件照常收到(Redis 背板);
  2. **竞争消费**:worker x2 下提交 N 个 run → 全部完成,且每个 run 的事件 seq 连续无重复;
  3. **两层互不影响**:加 worker 副本不需要重启 HTTP(本脚本只连两个 HTTP 副本,不动它们)。

前置:两个 rag-http 副本(:3101/:3102)+ 至少一个 rag-worker + 中间件栈。
用法:``uv run python tools/scaling_test.py``
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import httpx


def sse_events(response: httpx.Response) -> Iterator[tuple[str | None, dict[str, Any]]]:
    event: str | None = None
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"raw": raw}
                yield event, payload
            event = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data_lines.append(value)


def stream_run(
    client: httpx.Client, run_id: str, headers: dict[str, str]
) -> list[tuple[str | None, dict[str, Any]]]:
    frames: list[tuple[str | None, dict[str, Any]]] = []
    with client.stream("GET", f"/runs/{run_id}/stream", headers=headers, timeout=120) as resp:
        for event, payload in sse_events(resp):
            frames.append((event, payload))
            if event in ("run_completed", "run_failed"):
                break
    return frames


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http-a", default="http://localhost:3101/api")
    parser.add_argument("--http-b", default="http://localhost:3102/api")
    parser.add_argument("--runs", type=int, default=6)
    args = parser.parse_args()

    client_a = httpx.Client(base_url=args.http_a, timeout=120)
    client_b = httpx.Client(base_url=args.http_b, timeout=120)
    failures: list[str] = []

    username = f"scale_{uuid.uuid4().hex[:8]}"
    token = client_a.post(
        "/auth/register",
        json={"username": username, "password": "password123", "displayName": "Scale"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    print("== 1. 跨副本 SSE(副本 A 提交 / 副本 B 收事件) ==")
    submitted = client_a.post("/runs/demo", headers=headers).json()
    run_id = submitted["runId"]
    frames = stream_run(client_b, run_id, headers)
    events = [e for e, _ in frames]
    ok = events[:1] == ["run_started"] and events[-1] == "run_completed"
    print(f"  {'✓' if ok else '✗'} 副本 B 收到完整事件链: {events}")
    if not ok:
        failures.append("跨副本 SSE")

    print(f"== 2. 竞争消费(worker x2 下提交 {args.runs} 个 run) ==")
    run_ids: list[str] = []
    for _ in range(args.runs):
        run_ids.append(client_a.post("/runs/demo", headers=headers).json()["runId"])
    all_ok = True
    for rid in run_ids:
        fs = stream_run(client_b, rid, headers)
        types = [e for e, _ in fs]
        seqs = [p.get("sequenceNo") for _, p in fs]
        expected_seq = list(range(1, len(fs) + 1))
        run_ok = (
            types[-1] == "run_completed"
            and types.count("run_started") == 1
            and seqs == expected_seq
        )
        if not run_ok:
            all_ok = False
            print(f"  ✗ {rid}: types={types} seqs={seqs}")
    print(f"  {'✓' if all_ok else '✗'} {args.runs} 个 run 全部完成且事件 seq 连续无重复")
    if not all_ok:
        failures.append("竞争消费")

    print()
    if failures:
        print(f"失败项: {failures}")
        return 1
    print("独立扩缩容验证通过 ✅(跨副本 SSE + 竞争消费)")
    print(
        "提示:滚动重启不丢(run 不丢)可手工验证——提交 run 后 kill -TERM 一个 worker,重启后所有 run 仍完成。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
