"""agent 工具编排循环(自建,不依赖 LangGraph/LangChain)。

与 Node 版对齐(apps/node-server/src/modules/agent/agent-runner.service.ts):
- 每步都经 RunEngine.emit 落库 + 广播,形成可断线重连回放的审计轨迹:
  tool_called / tool_result(每次调工具)、final_answer(收敛);
- start/complete 由 RunProcessor 在外层统一包裹,这里只产出领域事件;
- 工具异常不让整个 run 崩,而是把错误文本喂回模型,让它自行纠偏/换路;
- 推理步数上限防工具调用死循环把上下文/费用打爆。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent_core.llm import LlmClient
from agent_core.run_engine import RunEngine, RunRecord
from agent_core.vector import MilvusVectorStore
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.modules.agent.tools import ToolContext, ToolRegistry
from rag_server.settings import Settings
from rag_server.shared.retrieval import RagRetriever

logger = logging.getLogger("rag_server.agent")

SYSTEM_PROMPT = "\n".join(
    [
        "你是一个能调用工具操作用户个人知识库的助手。",
        "可用工具:list_documents(看有哪些文档)、organize(按关键词筛某类文档)、",
        "summarize_document(概括某个文档)、retrieve_knowledge(语义检索资料片段)。",
        "请先用工具收集信息,再综合作答;最终回答要基于工具返回的真实内容,",
        "涉及具体文档时用「文档 N」标注来源,不要编造不存在的文档或内容。",
    ]
)


class AgentRunnerService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LlmClient,
        vector: MilvusVectorStore,
        run_engine: RunEngine,
        settings: Settings,
    ) -> None:
        self._llm = llm
        self._run_engine = run_engine
        self._settings = settings
        self._registry = ToolRegistry(
            session_factory=session_factory,
            llm=llm,
            retriever=RagRetriever(session_factory=session_factory, llm=llm, vector=vector),
            default_top_k=settings.rag_top_k,
        )

    async def run(self, run: RunRecord) -> None:
        ctx = ToolContext(user_id=run.user_id, run_id=run.run_id)
        tools = self._registry.schemas()
        messages: list[Any] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": run.task},
        ]

        for _ in range(self._settings.agent_max_iterations):
            message = await self._llm.chat_with_tools(messages, tools)
            messages.append(message)

            tool_calls = message.tool_calls or []
            if not tool_calls:
                await self._run_engine.emit(
                    run.run_id, "final_answer", {"content": message.content or ""}
                )
                return

            for call in tool_calls:
                if call.type != "function":
                    continue
                name = call.function.name
                args = self._parse_args(call.function.arguments)
                await self._run_engine.emit(run.run_id, "tool_called", {"name": name, "args": args})
                result = await self._exec_tool(name, args, ctx)
                await self._run_engine.emit(
                    run.run_id, "tool_result", {"name": name, "result": result[:2000]}
                )
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        # 兜底:达到步数上限仍未收敛,给前端一个终态 final_answer 而非悬挂
        logger.warning(
            "run=%s 达到最大推理步数 %s", run.run_id, self._settings.agent_max_iterations
        )
        await self._run_engine.emit(
            run.run_id,
            "final_answer",
            {"content": "(已达最大推理步数,未能得出最终答案)", "truncated": True},
        )

    async def _exec_tool(self, name: str, args: dict[str, Any], ctx: ToolContext) -> str:
        tool = self._registry.get(name)
        if tool is None:
            return f"错误:未知工具 {name}"
        try:
            return await tool.run(args, ctx)
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            logger.error("工具 %s 执行失败: %s", name, message)
            return f"工具执行失败:{message}"

    @staticmethod
    def _parse_args(raw: str | None) -> dict[str, Any]:
        """模型给的 arguments 是 JSON 字符串,可能为空或不合法,统一兜成 {}。"""
        try:
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
