"""Load documents and split them into chunks that can be cited.

Supported: .md / .txt (split on headings, then into ~180-word windows) and
.pptx (one chunk per slide, read straight from the slide XML, so no extra
dependency is needed).
"""

from __future__ import annotations

import html
import pathlib
import re
import zipfile
from dataclasses import dataclass

MAX_WORDS = 180
OVERLAP_WORDS = 40


@dataclass(frozen=True)
class Chunk:
    doc: str      # file name relative to the corpus root
    section: str  # heading or "slide N"
    text: str

    @property
    def cite(self) -> str:
        return f"{self.doc} › {self.section}"


def _windows(words: list[str]) -> list[str]:
    if len(words) <= MAX_WORDS:
        return [" ".join(words)]
    step = MAX_WORDS - OVERLAP_WORDS
    return [" ".join(words[i:i + MAX_WORDS]) for i in range(0, len(words) - OVERLAP_WORDS, step)]


def chunk_markdown(doc: str, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    section, buf = "intro", []
    in_code = False

    def flush():
        words = " ".join(buf).split()
        if words:
            chunks.extend(Chunk(doc, section, w) for w in _windows(words))

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        heading = re.match(r"^(#{1,4})\s+(.*)", line) if not in_code else None
        if heading:
            flush()
            section, buf = heading.group(2).strip(), []
        else:
            buf.append(line)
    flush()
    return chunks


def _slide_number(name: str) -> int:
    return int(re.search(r"(\d+)\.xml$", name).group(1))


def chunk_pptx(doc: str, path: pathlib.Path) -> list[Chunk]:
    chunks = []
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=_slide_number)
        for name in slides:
            xml = z.read(name).decode("utf-8", "ignore")
            runs = [html.unescape(t) for t in re.findall(r"<a:t>([^<]*)</a:t>", xml)]
            words = " ".join(runs).split()
            if len(words) >= 5:
                for w in _windows(words):
                    chunks.append(Chunk(doc, f"slide {_slide_number(name)}", w))
    return chunks


def load_corpus(root: str | pathlib.Path) -> list[Chunk]:
    root = pathlib.Path(root)
    chunks: list[Chunk] = []
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.suffix.lower() in {".md", ".txt"}:
            chunks += chunk_markdown(rel, path.read_text(encoding="utf-8", errors="ignore"))
        elif path.suffix.lower() == ".pptx":
            chunks += chunk_pptx(rel, path)
    return chunks
