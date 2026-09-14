"""契约层单测:camelCase 双向、wire 形状、未知字段忽略。"""

import pydantic
from rag_server.contracts import AgentDocument, RunEventRow, SendMessageReq, wire


def test_wire_camel_case() -> None:
    doc = AgentDocument.from_dict(
        {
            "id": 1,
            "filename": "报告.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": 10,
            "status": "ready",
            "chunkCount": 2,
            "createdAt": "2026-09-14T00:00:00.000Z",
            "updatedAt": "2026-09-14T00:00:00.000Z",
        }
    )
    out = wire(doc)
    assert out["mimeType"] == "application/pdf"
    assert out["chunkCount"] == 2
    assert "errorMsg" not in out  # 未设置的 optional 字段省略


def test_request_accepts_camel_case_alias() -> None:
    req = pydantic.TypeAdapter(SendMessageReq).validate_python({"query": "你好", "topK": 3})
    assert req.query == "你好"
    assert req.top_k == 3


def test_request_accepts_snake_case_too() -> None:
    req = pydantic.TypeAdapter(SendMessageReq).validate_python({"query": "你好", "top_k": 5})
    assert req.top_k == 5


def test_request_ignores_unknown_fields() -> None:
    # 对齐 Node 版 ValidationPipe(whitelist 丢弃未声明字段,不报错)
    req = pydantic.TypeAdapter(SendMessageReq).validate_python({"query": "你好", "isAdmin": True})
    assert req.query == "你好"
    assert not hasattr(req, "isAdmin")


def test_event_row_payload_is_plain_object() -> None:
    row = RunEventRow.from_dict(
        {
            "id": 3,
            "runId": "run-1",
            "sequenceNo": 2,
            "eventType": "tool_called",
            "payload": {"name": "retrieve_knowledge", "args": {"query": "X"}},
            "createdAt": "2026-09-14T00:00:00.000Z",
        }
    )
    out = wire(row)
    assert out["eventType"] == "tool_called"
    assert out["payload"] == {"name": "retrieve_knowledge", "args": {"query": "X"}}
    assert out["sequenceNo"] == 2
