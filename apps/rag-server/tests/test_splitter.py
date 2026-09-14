"""切分器单测(平移自 Node 版行为的等价性验证)。"""

from rag_server.modules.documents.splitter import SplitOptions, estimate_tokens, split_text


def test_short_text_single_chunk() -> None:
    chunks = split_text("这是一段短文本。", SplitOptions(chunk_size=800, chunk_overlap=100))
    assert chunks == ["这是一段短文本。"]


def test_long_text_split_within_chunk_size() -> None:
    text = "\n\n".join(["段落内容" * 20 for _ in range(30)])
    chunks = split_text(text, SplitOptions(chunk_size=200, chunk_overlap=20))
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # 内容不丢:所有非空白字符都应出现(切分不丢字)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_empty_and_whitespace() -> None:
    opts = SplitOptions(chunk_size=100, chunk_overlap=10)
    assert split_text("", opts) == []
    assert split_text("   \n\n   ", opts) == []


def test_no_separator_hard_split() -> None:
    text = "a" * 1000
    chunks = split_text(text, SplitOptions(chunk_size=300, chunk_overlap=30))
    assert len(chunks) >= 3
    assert all(len(c) <= 300 for c in chunks)


def test_estimate_tokens() -> None:
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("a" * 300) == 100
