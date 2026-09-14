"""文档解析:pdf / docx / md / txt → 纯文本(支持集与 Node 版一致)。

解析是 CPU 活(尤其 PDF):调用方(IngestionService)用 asyncio.to_thread 包住,
不阻塞 worker 事件循环。

docx 的坑(实测踩到):简历类文档常把全部内容放在**文本框**(w:txbxContent)里,
python-docx 的 paragraphs/tables 完全读不到(10k 字文本 → 0 字 → 静默摄取出 0 分片)。
故 docx 走 XML 级提取:递归收集所有 w:p(含文本框内),并剔除 mc:Fallback
(与 mc:Choice 重复的兼容副本,不去重会把内容抄两遍);同时覆盖页眉/页脚。
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile

SUPPORTED_EXTENSIONS = frozenset({"pdf", "docx", "md", "markdown", "txt"})
SUPPORTED_HINT = "仅支持 pdf / docx / md / txt"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


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
            text = "\n".join(
                doc.load_page(i).get_text()  # type: ignore[no-untyped-call]
                for i in range(doc.page_count)
            )
        finally:
            doc.close()  # type: ignore[no-untyped-call]
    elif ext == "docx":
        text = _parse_docx(data)
    else:
        text = data.decode("utf-8", errors="replace")

    if not text.strip():
        # 空文本不静默通过:摄取会以明确错误失败(而不是 ready + 0 分片)
        raise ValueError("未能从文档中提取到文本(可能是纯图片/扫描件或空文档)")
    return text


def _parse_docx(data: bytes) -> str:
    """提取 docx 全部可见文本(含文本框;覆盖页眉页脚)。"""
    lines: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = ["word/document.xml"]
        names += sorted(
            n for n in zf.namelist() if re.fullmatch(r"word/(header|footer)\d*\.xml", n)
        )
        for name in names:
            try:
                root = ET.fromstring(zf.read(name))
            except (KeyError, ET.ParseError):
                continue
            _drop_fallbacks(root)
            for para in root.iter(f"{_W}p"):
                line = "".join(t.text or "" for t in para.iter(f"{_W}t")).strip()
                if line:
                    lines.append(line)
    return "\n".join(lines)


def _drop_fallbacks(root: ET.Element) -> None:
    """删除 mc:Fallback 子树:它与 mc:Choice 内容重复(不去重会把文本抄两遍)。"""
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == f"{_MC}Fallback":
                parent.remove(child)
