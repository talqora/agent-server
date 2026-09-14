"""文档解析:pdf / docx / md / txt → 纯文本(支持集与 Node 版一致)。

解析是 CPU 活(尤其 PDF):调用方(IngestionService)用 asyncio.to_thread 包住,
不阻塞 worker 事件循环。
"""

from __future__ import annotations

import io

SUPPORTED_EXTENSIONS = frozenset({"pdf", "docx", "md", "markdown", "txt"})
SUPPORTED_HINT = "仅支持 pdf / docx / md / txt"


def extname(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot + 1 :].lower() if dot >= 0 else ""


def is_supported(filename: str) -> bool:
    return extname(filename) in SUPPORTED_EXTENSIONS


def parse_to_text(data: bytes, filename: str) -> str:
    """把上传文件的字节解析成纯文本。pdf/docx 走对应解析器,其余按 UTF-8 文本读。"""
    ext = extname(filename)
    if ext == "pdf":
        import pymupdf  # 延迟 import:进程启动不被重库拖慢

        doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
        try:
            return "\n".join(
                doc.load_page(i).get_text()  # type: ignore[no-untyped-call]
                for i in range(doc.page_count)
            )
        finally:
            doc.close()  # type: ignore[no-untyped-call]
    if ext == "docx":
        from docx import Document as DocxDocument

        docx = DocxDocument(io.BytesIO(data))
        return "\n".join(p.text for p in docx.paragraphs)
    return data.decode("utf-8", errors="replace")
