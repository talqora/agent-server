"""rag-server —— RAG 知识库服务(agent-server 的第一个服务)。

形态:HTTP 角色(uvicorn,HTTP + SSE)+ worker 角色(Pulsar 消费者),同一代码库两个入口。
契约:所有业务类型来自 proto 生成(rag_server.contracts),不手写平行 DTO。
"""

__version__ = "0.1.0"
