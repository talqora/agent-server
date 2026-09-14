"""服务内共享件(rag-server 专属,多服务公共机制在 agent-core)。

模块边界:modules/ 之间不直接互相依赖共享逻辑,横向依赖走本层或 agent-core。
"""
