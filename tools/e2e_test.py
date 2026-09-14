"""本地全链路端到端测试(真实全栈:PG / Redis / Pulsar / Milvus + LLM stub)。

覆盖:
  1. 注册 → 登录态(/auth/me)
  2. 上传文档(**中文文件名**)→ 摄取 run 的 SSE 进度(step → run_completed)
  3. 文档就绪(status=ready / chunkCount>0)
  4. 对话流式 SSE(token 逐字 → done 带 citations)
  5. 任务会话 + agent 任务 → 工具调用事件链(tool_called → tool_result → final_answer)
  6. 会话详情回放(落库行形状校验)+ SSE 断线补发(Last-Event-ID / ?access_token=)

前置:中间件栈(compose dev)+ llm-stub + rag-http + rag-worker 已启动。
用法(仓库根):``uv run python tools/e2e_test.py``
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import httpx

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name}" + (f"  [{detail}]" if detail and not ok else ""))


def sse_events(response: httpx.Response) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """解析 text/event-stream:产出 (event, data)。"""
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
    """订阅 run 事件流直到终态,返回全部帧。"""
    frames: list[tuple[str | None, dict[str, Any]]] = []
    with client.stream("GET", f"/runs/{run_id}/stream", headers=headers, timeout=120) as resp:
        for event, payload in sse_events(resp):
            frames.append((event, payload))
            if event in ("run_completed", "run_failed"):
                break
    return frames


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:3101/api")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base, timeout=120)

    print("== 1. 注册 / 鉴权 ==")
    username = f"e2e_{uuid.uuid4().hex[:8]}"
    reg = client.post(
        "/auth/register",
        json={"username": username, "password": "password123", "displayName": "E2E 测试"},
    )
    check("注册 201", reg.status_code == 201, reg.text[:200])
    token = reg.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    login = client.post("/auth/login", json={"username": username, "password": "password123"})
    check("登录 200", login.status_code == 200, login.text[:200])

    me = client.get("/auth/me", headers=headers)
    check("me 返回 camelCase", me.status_code == 200 and "displayName" in me.json(), me.text[:200])

    bad = client.get("/auth/me", headers={"Authorization": "Bearer bad-token"})
    check("无效 token 401", bad.status_code == 401, str(bad.status_code))

    print("== 2. 上传文档(中文文件名)+ 摄取 SSE ==")
    content = "# 端到端测试文档\n\n" + ("这是用于端到端测试的中文段落,涵盖检索链路验证。" * 120)
    files = {"file": ("端到端测试文档.md", content.encode("utf-8"), "text/markdown")}
    up = client.post("/documents", headers=headers, files=files)
    check("上传 201", up.status_code == 201, up.text[:200])
    document_id = up.json()["documentId"]
    run_id = up.json()["runId"]

    frames = stream_run(client, run_id, headers)
    event_types = [e for e, _ in frames]
    check("摄取收到 run_started", event_types[:1] == ["run_started"], str(event_types[:3]))
    check("摄取含 step 事件", "step" in event_types, str(event_types))
    check("摄取以 run_completed 收尾", event_types[-1] == "run_completed", str(event_types[-2:]))

    doc = client.get(f"/documents/{document_id}", headers=headers).json()
    check(
        "文档 ready 且有分片",
        doc["status"] == "ready" and doc["chunkCount"] > 0,
        json.dumps(doc, ensure_ascii=False)[:200],
    )

    print("== 3. SSE 断线补发(Last-Event-ID / ?access_token=) ==")
    replay_headers = {**headers, "Last-Event-ID": "3"}
    with client.stream("GET", f"/runs/{run_id}/stream", headers=replay_headers, timeout=60) as resp:
        replayed = [p for _, p in sse_events(resp)]
    seqs = [p["sequenceNo"] for p in replayed]
    check(
        "补发从 4 开始且到终态",
        seqs[:1] == [4] and replayed[-1]["eventType"] == "run_completed",
        str(seqs),
    )

    with client.stream(
        "GET", f"/runs/{run_id}/stream", params={"access_token": token}, timeout=60
    ) as resp:
        via_query = [p for _, p in sse_events(resp)]
    check(
        "?access_token= 兜底可用",
        len(via_query) > 0 and via_query[-1]["eventType"] == "run_completed",
    )

    print("== 4. 对话流式 SSE ==")
    conv = client.post("/conversations", headers=headers, json={"title": "新对话"})
    check("建会话 201", conv.status_code == 201, conv.text[:200])
    conversation_id = conv.json()["id"]

    tokens: list[str] = []
    done_payload: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    with client.stream(
        "POST",
        f"/conversations/{conversation_id}/messages",
        headers=headers,
        json={"query": "这份文档讲了什么?", "topK": 6},
        timeout=120,
    ) as resp:
        for event, payload in sse_events(resp):
            if event == "token":
                tokens.append(str(payload.get("value", "")))
            elif event == "done":
                done_payload = payload
                break
            elif event == "error":
                error_payload = payload
                break
    check(
        "对话无错误帧",
        error_payload is None,
        json.dumps(error_payload, ensure_ascii=False)[:200] if error_payload else "",
    )
    check("逐 token 输出非空", len(tokens) > 0, f"tokens={len(tokens)}")
    check(
        "done 帧含 messageId + citations",
        bool(done_payload)
        and "messageId" in done_payload
        and isinstance(done_payload.get("citations"), list),
        json.dumps(done_payload, ensure_ascii=False)[:200] if done_payload else "",
    )

    conv_detail = client.get(f"/conversations/{conversation_id}", headers=headers).json()
    check(
        "会话历史含两轮消息",
        len(conv_detail["messages"]) >= 2,
        str(len(conv_detail.get("messages", []))),
    )
    check("会话标题已回填", conv_detail["title"] == "这份文档讲了什么?", conv_detail["title"])

    print("== 5. agent 任务(工具调用链) ==")
    ts = client.post("/agent/sessions", headers=headers, json={"title": "新任务会话"})
    check("建任务会话 201", ts.status_code == 201, ts.text[:200])
    session_id = ts.json()["id"]

    task = client.post(
        "/agent/tasks",
        headers=headers,
        json={"task": "帮我看看有哪些文档", "sessionId": session_id},
    )
    check("提交任务 202", task.status_code == 202, task.text[:200])
    task_run_id = task.json()["runId"]

    task_frames = stream_run(client, task_run_id, headers)
    task_types = [e for e, _ in task_frames]
    check(
        "工具链完整",
        {"tool_called", "tool_result", "final_answer"} <= set(task_types),
        str(task_types),
    )
    check("任务以 run_completed 收尾", task_types[-1] == "run_completed", str(task_types[-2:]))

    detail = client.get(f"/agent/sessions/{session_id}", headers=headers).json()
    run0 = detail["runs"][0]
    ev0 = run0["events"][0]
    expected_keys = {"id", "runId", "sequenceNo", "eventType", "payload", "createdAt"}
    check("会话详情事件为落库行形状", expected_keys <= set(ev0.keys()), str(sorted(ev0.keys())))
    check("run.task 回填", run0.get("task") == "帮我看看有哪些文档", str(run0.get("task")))
    check("会话标题回填", detail["title"] == "帮我看看有哪些文档", detail["title"])

    print("== 6. 清理(删文档:Milvus + PG + 磁盘) ==")
    dele = client.delete(f"/documents/{document_id}", headers=headers)
    check("删文档 204", dele.status_code == 204, str(dele.status_code))
    gone = client.get(f"/documents/{document_id}", headers=headers)
    check("删后 404", gone.status_code == 404, str(gone.status_code))

    print()
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
    if FAIL:
        print("失败项:")
        for name in FAIL:
            print(f"  - {name}")
        return 1
    print("E2E 全链路通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
