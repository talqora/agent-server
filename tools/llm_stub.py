"""本地 LLM stub:OpenAI 兼容协议(chat / 流式 / 工具调用 / embeddings)的确定性模拟。

用途:本机没有 Ollama 或真实 API key 时,支撑 rag-server 的**完整本地端到端测试**:
- ``POST /v1/chat/completions``:请求带 tools 且还没有工具结果 → 先返回一次 tool_call
  (触发 agent 工具循环);否则给最终回答。stream=true 时按 SSE 逐 token 返回。
- ``POST /v1/embeddings``:确定性伪向量(sha256 播种 + 归一化),维度默认 768
  (与 MILVUS_VECTOR_SIZE 一致),供摄取链路真实走通 Milvus 双写。

用法(仓库根):``uv run python tools/llm_stub.py``  # 监听 :11434,与 Ollama 默认端口一致
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

EMBED_DIM = 768
STREAM_TEXT = "这是一段本地端到端测试用的流式回答,用于验证 SSE 逐 token 推送链路。"
FINAL_TEXT = "这是本地端到端测试用的回答。(llm-stub)"

app = FastAPI(title="llm-stub")


def _tokens(text: str) -> list[str]:
    """把文本切成小片段模拟逐 token 输出。"""
    step = 3
    return [text[i : i + step] for i in range(0, len(text), step)] or [text]


def _tool_default_args(name: str) -> dict[str, Any]:
    if name == "retrieve_knowledge":
        return {"query": "本地端到端测试"}
    if name == "summarize_document":
        return {"documentId": 1}
    if name == "organize":
        return {"keyword": "测试"}
    return {}


def _vector(text: str) -> list[float]:
    """确定性伪向量:同一文本恒得同一向量(供检索链路自洽)。"""
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rnd = random.Random(seed)
    vec = [rnd.uniform(-1.0, 1.0) for _ in range(EMBED_DIM)]
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    body: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    tools: list[dict[str, Any]] | None = body.get("tools")
    model: str = body.get("model", "stub-model")
    created = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    has_tool_result = any(m.get("role") == "tool" for m in messages)
    tool_calls: list[dict[str, Any]] | None = None
    if tools and not has_tool_result:
        first_tool = tools[0]["function"]["name"]
        tool_calls = [
            {
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": first_tool,
                    "arguments": json.dumps(_tool_default_args(first_tool), ensure_ascii=False),
                },
            }
        ]

    if body.get("stream"):

        async def gen() -> AsyncIterator[str]:
            for token in _tokens(STREAM_TEXT):
                payload = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            stop = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(stop, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    message: dict[str, Any] = {
        "role": "assistant",
        "content": None if tool_calls else FINAL_TEXT,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    return JSONResponse(
        {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    inputs = body.get("input")
    if isinstance(inputs, str):
        inputs = [inputs]
    data = [
        {"object": "embedding", "index": i, "embedding": _vector(str(text))}
        for i, text in enumerate(inputs or [])
    ]
    return JSONResponse(
        {
            "object": "list",
            "data": data,
            "model": body.get("model", "stub-embed"),
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11434)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
