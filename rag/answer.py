"""Answer a question from retrieved chunks, with numbered citations.

Two generators:
  * ClaudeGenerator  - calls the Claude API (Anthropic Python SDK). It uses
    adaptive thinking, an explicit effort level, and server-side refusal
    fallbacks (`fallbacks="default"`: if the requested model declines, the API
    re-runs the request on a fallback model inside the same call).
  * ExtractiveGenerator - offline, no API key needed: picks the sentences
    that share the most query terms and cites where they came from.

Both return an Answer whose citations are checked against the sources that
were actually supplied, so a citation like [7] with only 5 sources is caught.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ingest import Chunk
from .retrieval import tokenize

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You answer questions using only the numbered sources supplied in the user message.

Rules:
- Every sentence that states a fact from the sources ends with its citation, e.g. [2] or [1][3].
- If the sources do not contain the answer, say so in one sentence and do not guess. Partial answers are fine \
when you say which part is missing.
- Keep the answer short: at most 5 sentences, plain text, no headings.
- Answer in the language of the question."""


@dataclass
class Answer:
    text: str
    sources: list[Chunk]
    generator: str
    notes: list[str] = field(default_factory=list)

    @property
    def cited(self) -> set[int]:
        return {int(n) for n in re.findall(r"\[(\d+)\]", self.text)}

    @property
    def invalid_citations(self) -> set[int]:
        return {n for n in self.cited if not 1 <= n <= len(self.sources)}


def format_sources(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[{i}] ({c.cite})\n{c.text}" for i, c in enumerate(chunks, 1))


class ExtractiveGenerator:
    name = "extractive (offline)"

    def __init__(self, max_sentences: int = 3):
        self.max_sentences = max_sentences

    def answer(self, question: str, chunks: list[Chunk]) -> Answer:
        terms = set(tokenize(question))
        candidates = []
        for i, chunk in enumerate(chunks, 1):
            for pos, sentence in enumerate(re.split(r"(?<=[.!?])\s+|\s+\|\s+", chunk.text)):
                overlap = len(terms & set(tokenize(sentence)))
                if overlap and len(sentence.split()) >= 4:
                    # earlier sources and earlier sentences win ties
                    candidates.append((overlap, -i, -pos, sentence.strip(), i))
        candidates.sort(reverse=True)
        if not candidates:
            return Answer("The indexed documents do not contain an answer to this question.", chunks, self.name)
        picked = candidates[: self.max_sentences]
        text = " ".join(f"{s} [{i}]" for *_, s, i in picked)
        return Answer(text, chunks, self.name)


class ClaudeGenerator:
    name = f"claude ({MODEL})"

    def __init__(self, client=None, effort: str = "medium"):
        import anthropic  # imported here so the offline mode works without the package

        self.anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.effort = effort

    def answer(self, question: str, chunks: list[Chunk]) -> Answer:
        if not chunks:
            return Answer("No indexed document matches this question.", chunks, self.name)
        user = f"Sources:\n\n{format_sources(chunks)}\n\nQuestion: {question}"
        response = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
            messages=[{"role": "user", "content": user}],
        )
        notes = []
        for block in response.content:
            if block.type == "fallback":
                notes.append(f"{block.from_.model} declined; {block.to.model} answered")
        if response.stop_reason == "refusal":
            return Answer("The model declined to answer this question.", chunks, self.name, notes + ["refusal"])
        if response.stop_reason == "max_tokens":
            notes.append("answer cut off at max_tokens")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return Answer(text, chunks, f"claude ({response.model})", notes)


def make_generator(prefer_claude: bool = True):
    """Claude when credentials are available, otherwise the offline generator."""
    if prefer_claude:
        try:
            gen = ClaudeGenerator()
        except ImportError:  # anthropic package not installed
            return ExtractiveGenerator()
        if gen.client.api_key or gen.client.auth_token:
            return gen
    return ExtractiveGenerator()


def ask(question: str, retriever, generator, k: int = 5) -> Answer:
    chunks = [c for _, c in retriever.search(question, k=k)]
    if isinstance(generator, ClaudeGenerator):
        a = generator.anthropic
        try:
            return generator.answer(question, chunks)
        except a.AuthenticationError:
            note = "Claude: invalid API key"
        except a.RateLimitError:
            note = "Claude: rate limited"
        except a.APIStatusError as e:
            note = f"Claude: API error {e.status_code}"
        except a.APIConnectionError:
            note = "Claude: network error"
        fallback = ExtractiveGenerator().answer(question, chunks)
        fallback.notes.append(f"{note}; used the offline extractive answer instead")
        return fallback
    return generator.answer(question, chunks)
