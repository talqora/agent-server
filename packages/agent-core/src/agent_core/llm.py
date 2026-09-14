"""LLM 客户端(OpenAI 兼容协议):chat / 流式 / 工具调用 / embedding。

与 Node 版对齐(apps/node-server/src/shared/llm/llm.service.ts):
- 只走 OpenAI 兼容协议(千问 DashScope / Ollama / DeepSeek 等),业务代码不感知厂商;
- chat 默认非流式;需要流式时用 chat_stream(AsyncIterator 逐 token);
- embed 批处理(减少 HTTP 往返)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)


class LlmClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        chat_model: str,
        embed_model: str,
        timeout_s: float = 120.0,
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)
        self.chat_model = chat_model
        self.embed_model = embed_model

    async def chat(self, messages: Iterable[ChatCompletionMessageParam]) -> str:
        """非流式 chat,返回 assistant 文本。"""
        resp = await self._client.chat.completions.create(
            model=self.chat_model, messages=list(messages), stream=False
        )
        return resp.choices[0].message.content or ""

    async def chat_stream(
        self, messages: Iterable[ChatCompletionMessageParam]
    ) -> AsyncIterator[str]:
        """流式 chat:逐 token 产出 delta.content(供 SSE 边生成边推)。"""
        stream = await self._client.chat.completions.create(
            model=self.chat_model, messages=list(messages), stream=True
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def chat_with_tools(
        self,
        messages: Iterable[ChatCompletionMessageParam],
        tools: list[ChatCompletionToolParam],
    ) -> ChatCompletionMessage:
        """带工具的非流式 chat:返回原始 assistant 消息(可能带 tool_calls 或 content)。"""
        resp = await self._client.chat.completions.create(
            model=self.chat_model, messages=list(messages), tools=tools, stream=False
        )
        return resp.choices[0].message

    async def embed(self, input: str | list[str]) -> list[list[float]]:
        """批量 embedding;单字符串自动包成列表。"""
        batch = [input] if isinstance(input, str) else input
        resp = await self._client.embeddings.create(model=self.embed_model, input=batch)
        return [list(d.embedding) for d in resp.data]

    async def close(self) -> None:
        await self._client.close()


__all__: list[str] = [
    "ChatCompletionMessage",
    "ChatCompletionMessageParam",
    "ChatCompletionToolParam",
    "LlmClient",
]
