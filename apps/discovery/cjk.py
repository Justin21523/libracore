from __future__ import annotations

import re

import jieba
from opencc import OpenCC

_to_simplified = OpenCC("t2s")
_to_traditional = OpenCC("s2t")
_punctuation = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)


def normalize_text(value: str) -> str:
    lowered = value.casefold()
    normalized = _punctuation.sub(" ", lowered)
    return " ".join(normalized.split())


def cjk_variants(value: str) -> set[str]:
    base = normalize_text(value)
    simplified = normalize_text(_to_simplified.convert(value))
    traditional = normalize_text(_to_traditional.convert(value))
    return {variant for variant in [base, simplified, traditional] if variant}


def tokenize_cjk(value: str) -> str:
    tokens: set[str] = set()
    for variant in cjk_variants(value):
        tokens.update(token.strip() for token in jieba.cut(variant) if token.strip())
    return " ".join(sorted(tokens))


def normalize_query(value: str) -> tuple[str, str]:
    normalized = " ".join(sorted(cjk_variants(value)))
    tokens = tokenize_cjk(value)
    return normalized, tokens

