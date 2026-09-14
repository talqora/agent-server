"""文档模块单测:中文文件名还原、解析器支持集。"""

from rag_server.modules.documents.parser import extname, is_supported, parse_to_text
from rag_server.modules.documents.service import normalize_filename


def test_normalize_filename_ascii_noop() -> None:
    assert normalize_filename("report.pdf") == "report.pdf"


def test_normalize_filename_utf8_kept() -> None:
    # 已经是正确的 UTF-8 字符串:encode('latin-1') 失败 → 原样返回
    assert normalize_filename("端到端测试文档.md") == "端到端测试文档.md"


def test_normalize_filename_latin1_mojibake_recovered() -> None:
    # 模拟 multipart 解析器按 latin-1 解 UTF-8 字节后的乱码
    mojibake = "端到端测试文档.md".encode().decode("latin-1")
    assert normalize_filename(mojibake) == "端到端测试文档.md"


def test_parser_support_set() -> None:
    assert is_supported("a.PDF") and is_supported("b.docx") and is_supported("c.md")
    assert is_supported("d.markdown") and is_supported("e.txt")
    assert not is_supported("f.exe") and not is_supported("noext")
    assert extname("dir/文件.TXT") == "txt"


def test_parse_markdown_and_txt() -> None:
    data = "# 标题\n\n正文内容".encode()
    assert parse_to_text(data, "x.md") == "# 标题\n\n正文内容"
    assert parse_to_text(data, "x.txt") == "# 标题\n\n正文内容"
