"""Evaluate retrieval (hit@1, hit@3, MRR) and answers (key fact, citations).

Retrieval: a question counts as a hit@k when one of its gold (document,
section) pairs is among the top-k chunks. MRR = mean of 1 / rank of the first
gold chunk (0 if not in the top 10).

Answers: "key fact" = the answer contains the expected fact string
(case-insensitive); "valid citations" = every [n] refers to a supplied source.

Usage:
  python -m eval.run_eval                      # retrieval + offline answers
  python -m eval.run_eval --generator claude   # also needs ANTHROPIC_API_KEY
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time

from rag.answer import ClaudeGenerator, ExtractiveGenerator, ask
from rag.ingest import load_corpus
from rag.retrieval import BM25, KeywordOverlap

HERE = pathlib.Path(__file__).resolve().parent


def load_questions():
    return [json.loads(line) for line in (HERE / "questions.jsonl").read_text().splitlines() if line.strip()]


def retrieval_metrics(retriever, questions):
    hit1 = hit3 = rr = 0.0
    misses = []
    for q in questions:
        gold = {tuple(g) for g in q["gold"]}
        ranked = [(c.doc, c.section) for _, c in retriever.search(q["question"], k=10)]
        rank = next((i for i, r in enumerate(ranked, 1) if r in gold), None)
        hit1 += rank == 1
        hit3 += rank is not None and rank <= 3
        rr += 1 / rank if rank else 0
        if rank != 1:
            misses.append((q["question"], rank, ranked[0] if ranked else None))
    n = len(questions)
    return {"hit@1": hit1 / n, "hit@3": hit3 / n, "mrr": rr / n}, misses


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(HERE.parent / "corpus"))
    ap.add_argument("--generator", choices=["extractive", "claude"], default="extractive")
    args = ap.parse_args()

    chunks = load_corpus(args.corpus)
    questions = load_questions()
    report = {"chunks": len(chunks), "questions": len(questions), "retrieval": {}}

    variants = [
        ("bm25_stemmed", BM25(chunks, stemming=True)),
        ("bm25_plain", BM25(chunks, stemming=False)),
        ("keyword_overlap", KeywordOverlap(chunks)),
    ]
    for name, retriever in variants:
        metrics, misses = retrieval_metrics(retriever, questions)
        report["retrieval"][name] = metrics
        if name == "bm25_stemmed":
            report["bm25_misses"] = [{"question": q, "gold_rank": r, "top1": t} for q, r, t in misses]

    generator = ClaudeGenerator() if args.generator == "claude" else ExtractiveGenerator()
    bm25 = BM25(chunks)
    rows = []
    t0 = time.perf_counter()
    for q in questions:
        ans = ask(q["question"], bm25, generator, k=5)
        rows.append({
            "question": q["question"],
            "answer": ans.text,
            "generator": ans.generator,
            "key_fact": q["key_fact"].lower() in ans.text.lower(),
            "valid_citations": bool(ans.cited) and not ans.invalid_citations,
            "notes": ans.notes,
        })
    elapsed = time.perf_counter() - t0
    n = len(rows)
    report["answers"] = {
        "generator": rows[0]["generator"] if rows else args.generator,
        "key_fact_rate": sum(r["key_fact"] for r in rows) / n,
        "valid_citation_rate": sum(r["valid_citations"] for r in rows) / n,
        "seconds_total": round(elapsed, 2),
    }

    out = HERE.parent / "results"
    out.mkdir(exist_ok=True)
    (out / f"eval_{args.generator}.json").write_text(json.dumps({**report, "rows": rows}, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
