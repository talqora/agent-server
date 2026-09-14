"""SSE 帧构造(手写帧,用于 POST 带 body 的流式接口)。"""

from __future__ import annotations

import json
from typing import Any


def sse_frame(event: str, data: dict[str, Any]) -> str:
    """构造一帧 SSE:``event: <name>\\ndata: <json>\\n\\n``(与 Node 版帧格式一致)。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
