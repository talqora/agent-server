"""递归字符切分:按分隔符层级(段落→行→空格→字符)尽量在自然边界处断开。

行为对齐 Node 版自研切分器(apps/node-server/src/modules/documents/text-splitter.ts),
即 LangChain RecursiveCharacterTextSplitter 的语义:把长文切成不超过 chunk_size 的块,
相邻块保留 chunk_overlap 重叠,让跨块的句子在检索时仍能命中上下文。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 默认分隔符层级:先按段落分,再行,再空格,最后单字符
DEFAULT_SEPARATORS: list[str] = ["\n\n", "\n", " ", ""]


@dataclass(frozen=True)
class SplitOptions:
    chunk_size: int
    chunk_overlap: int
    separators: list[str] | None = None


def split_text(text: str, opts: SplitOptions) -> list[str]:
    separators = opts.separators if opts.separators is not None else DEFAULT_SEPARATORS
    return [c for c in _split_recursive(text, separators, opts) if c.strip() != ""]


def estimate_tokens(text: str) -> int:
    """粗估 token 数:英文约 4 字符/token,中文偏 1,折中用 /3,仅用于元数据展示。"""
    return max(1, math.ceil(len(text) / 3))


def _split_recursive(text: str, separators: list[str], opts: SplitOptions) -> list[str]:
    final_chunks: list[str] = []

    # 选定本层分隔符:第一个在文中出现的;都不在则退到末位(通常是 "")
    separator = separators[-1]
    remaining: list[str] = []
    for i, s in enumerate(separators):
        if s == "":
            separator = s
            break
        if s in text:
            separator = s
            remaining = separators[i + 1 :]
            break

    splits = list(text) if separator == "" else text.split(separator)

    good_splits: list[str] = []
    for part in splits:
        if len(part) < opts.chunk_size:
            good_splits.append(part)
            continue
        # 单段已超长:先把攒着的合并出块,再对这段用更细的分隔符递归
        if good_splits:
            final_chunks.extend(_merge_splits(good_splits, separator, opts))
            good_splits = []
        if not remaining:
            final_chunks.append(part)
        else:
            final_chunks.extend(_split_recursive(part, remaining, opts))
    if good_splits:
        final_chunks.extend(_merge_splits(good_splits, separator, opts))
    return final_chunks


def _merge_splits(splits: list[str], separator: str, opts: SplitOptions) -> list[str]:
    """把若干小片用分隔符拼回不超过 chunk_size 的块,跨块滑窗保留 overlap。"""
    sep_len = len(separator)
    docs: list[str] = []
    window: list[str] = []
    total = 0

    def join() -> str:
        return separator.join(window).strip()

    for part in splits:
        add_len = len(part) + (sep_len if window else 0)
        if total + add_len > opts.chunk_size and window:
            doc = join()
            if doc:
                docs.append(doc)
            # 退栈:腾到能放下新片且重叠不超过 chunk_overlap
            while window and (total > opts.chunk_overlap or total + add_len > opts.chunk_size):
                total -= len(window[0]) + (sep_len if len(window) > 1 else 0)
                window.pop(0)
        window.append(part)
        total += len(part) + (sep_len if len(window) > 1 else 0)

    doc = join()
    if doc:
        docs.append(doc)
    return docs
