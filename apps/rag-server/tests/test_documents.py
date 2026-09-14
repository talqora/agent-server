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


def test_empty_text_rejected() -> None:
    # 空文档不静默通过(否则会"摄取成功但 0 分片")
    import pytest

    with pytest.raises(ValueError, match="未能从文档中提取到文本"):
        parse_to_text(b"   \n  ", "empty.txt")


def test_docx_textbox_extraction_and_fallback_dedup() -> None:
    """回归:简历类 docx 内容全在文本框(w:txbxContent),python-docx 读不到;
    且 mc:AlternateContent 的 Fallback 与 Choice 重复,必须去重。"""
    import io
    import zipfile

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    document_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{W}" xmlns:mc="{MC}">
  <w:body>
    <w:p><w:r><w:t>普通段落文本</w:t></w:r></w:p>
    <mc:AlternateContent>
      <mc:Choice>
        <w:txbxContent><w:p><w:r><w:t>文本框里的简历内容</w:t></w:r></w:p></w:txbxContent>
      </mc:Choice>
      <mc:Fallback>
        <w:txbxContent><w:p><w:r><w:t>文本框里的简历内容</w:t></w:r></w:p></w:txbxContent>
      </mc:Fallback>
    </mc:AlternateContent>
  </w:body>
</w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", document_xml)

    text = parse_to_text(buf.getvalue(), "简历.docx")
    assert "普通段落文本" in text
    assert "文本框里的简历内容" in text
    assert text.count("文本框里的简历内容") == 1  # Fallback 已剔除,不重复
