"""Command line: python -m rag.cli --corpus corpus "your question"

Uses Claude when ANTHROPIC_API_KEY (or another Anthropic credential) is set,
otherwise answers offline with the extractive generator. --offline forces
offline mode.
"""

from __future__ import annotations

import argparse
import time

from .answer import ExtractiveGenerator, ask, make_generator
from .ingest import load_corpus
from .retrieval import BM25


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask questions about a folder of documents.")
    ap.add_argument("question")
    ap.add_argument("--corpus", default="corpus", help="folder with .md, .txt or .pptx files")
    ap.add_argument("-k", type=int, default=5, help="number of chunks to retrieve")
    ap.add_argument("--offline", action="store_true", help="never call the Claude API")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    args = ap.parse_args()

    t0 = time.perf_counter()
    chunks = load_corpus(args.corpus)
    retriever = BM25(chunks)
    generator = ExtractiveGenerator() if args.offline else make_generator()
    if hasattr(generator, "effort"):
        generator.effort = args.effort
    t1 = time.perf_counter()
    answer = ask(args.question, retriever, generator, k=args.k)
    t2 = time.perf_counter()

    print(answer.text, "\n")
    for i, c in enumerate(answer.sources, 1):
        mark = "*" if i in answer.cited else " "
        print(f" {mark}[{i}] {c.cite}")
    for note in answer.notes:
        print(f"note: {note}")
    if answer.invalid_citations:
        print(f"warning: citations without a source: {sorted(answer.invalid_citations)}")
    print(f"\n{len(chunks)} chunks indexed in {(t1 - t0) * 1000:.0f} ms · answered in {(t2 - t1) * 1000:.0f} ms "
          f"· generator: {answer.generator}")


if __name__ == "__main__":
    main()
