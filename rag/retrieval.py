"""Okapi BM25 retrieval written from scratch, plus a keyword-overlap baseline.

BM25 score of document d for query q:
    sum over terms t in q of  IDF(t) * f(t,d) * (k1 + 1) / (f(t,d) + k1 * (1 - b + b * |d| / avgdl))
with IDF(t) = ln(1 + (N - n_t + 0.5) / (n_t + 0.5)).
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .ingest import Chunk

STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "has", "have", "how", "i", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to", "was", "what", "when", "where", "which", "who", "why", "will", "with", "you", "your", "le", "la", "les", "de", "des", "du", "un", "une", "et", "en", "est", "pour", "que", "qui", "der", "die", "das", "und", "ist", "ein", "eine", "zu", "mit"}


def stem(token: str) -> str:
    """Very light English suffix stripping (plural, -ing, -ed). Not Porter; enough to match
    'attackers' with 'attacker' or 'identifiers' with 'identifier'."""
    if len(token) <= 4 or not token.isalpha() or token.endswith(("us", "is", "ss")):
        return token
    for suffix, repl in (("ies", "y"), ("sses", "ss"), ("ing", ""), ("ed", ""), ("es", "e"), ("s", "")):
        if token.endswith(suffix) and not token.endswith("ss") and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)] + repl
    return token


def tokenize(text: str, stemming: bool = False) -> list[str]:
    tokens = re.findall(r"[a-zà-ÿ0-9]+(?:[-_.][a-zà-ÿ0-9]+)*", text.lower())
    tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 1]
    return [stem(t) for t in tokens] if stemming else tokens


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75, stemming: bool = True):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.stemming = stemming
        # index the section title too: headings are strong signals
        self.docs = [Counter(tokenize(f"{c.section} {c.text}", stemming)) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avgdl = sum(self.lengths) / max(len(self.lengths), 1)
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - k + 0.5) / (k + 0.5)) for t, k in df.items()}

    def search(self, query: str, k: int = 5) -> list[tuple[float, Chunk]]:
        terms = tokenize(query, self.stemming)
        scored = []
        for i, doc in enumerate(self.docs):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avgdl)
            for t in terms:
                f = doc.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(s, self.chunks[i]) for s, i in scored[:k]]


class KeywordOverlap:
    """Baseline: count of distinct query terms present in the chunk."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.docs = [set(tokenize(f"{c.section} {c.text}")) for c in chunks]

    def search(self, query: str, k: int = 5) -> list[tuple[float, Chunk]]:
        terms = set(tokenize(query))
        scored = sorted(
            ((len(terms & d), i) for i, d in enumerate(self.docs) if terms & d), key=lambda x: (-x[0], x[1])
        )
        return [(float(s), self.chunks[i]) for s, i in scored[:k]]
