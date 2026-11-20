"""Tests for chunking, BM25, the offline generator and the Claude request path.

The Claude path is tested against a local stub HTTP server, so the real SDK
serialises the request (model, beta header, fallbacks, thinking, effort) and
parses the response. No API key or network is needed.
"""

import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic
import pytest

from rag.answer import FALLBACK_BETA, MODEL, ClaudeGenerator, ExtractiveGenerator, ask
from rag.ingest import Chunk, chunk_markdown, chunk_pptx
from rag.retrieval import BM25, tokenize

CHUNKS = [
    Chunk("k8s.md", "HPA", "The Horizontal Pod Autoscaler scales replicas based on CPU utilisation."),
    Chunk("k8s.md", "Service", "A Service gives a stable virtual IP to a set of pods selected by labels."),
    Chunk("docker.md", "Images", "A Docker image is built in layers from a Dockerfile."),
]


# ---------------------------------------------------------------- ingest / retrieval

def test_markdown_chunks_follow_headings_and_skip_code_headings():
    md = "# Title\nintro text here\n## Part A\nalpha beta gamma\n```\n# not a heading\n```\n## Part B\ndelta"
    sections = [c.section for c in chunk_markdown("x.md", md)]
    assert sections == ["Title", "Part A", "Part B"]


def test_long_sections_are_windowed_with_overlap():
    md = "# S\n" + " ".join(f"w{i}" for i in range(400))
    chunks = chunk_markdown("x.md", md)
    assert len(chunks) == 3
    assert chunks[1].text.split()[0] == "w140"  # step = 180 - 40


def test_pptx_one_chunk_per_slide_in_numeric_order(tmp_path):
    path = tmp_path / "deck.pptx"
    with zipfile.ZipFile(path, "w") as z:
        for n in (10, 2):
            z.writestr(f"ppt/slides/slide{n}.xml", f"<p><a:t>slide number {n} talks about kubernetes &amp; pods</a:t></p>")
    chunks = chunk_pptx("deck.pptx", path)
    assert [c.section for c in chunks] == ["slide 2", "slide 10"]
    assert "kubernetes & pods" in chunks[0].text


def test_tokenizer_keeps_technical_terms():
    assert "ed25519" in tokenize("Ed25519 keys")
    assert "did:key" not in tokenize("did:key")  # colon splits
    assert "p95" in tokenize("the p95 latency")


def test_bm25_ranks_relevant_chunk_first_and_ignores_unrelated():
    bm = BM25(CHUNKS)
    assert bm.search("how does the autoscaler scale replicas")[0][1].section == "HPA"
    assert bm.search("quantum chromodynamics") == []


# ---------------------------------------------------------------- offline generator

def test_extractive_answer_cites_valid_sources():
    ans = ExtractiveGenerator().answer("What does a Service give to pods?", CHUNKS)
    assert ans.cited and not ans.invalid_citations
    assert "[2]" in ans.text


def test_invalid_citation_detected():
    from rag.answer import Answer

    assert Answer("x [1] y [4]", CHUNKS, "t").invalid_citations == {4}


# ---------------------------------------------------------------- Claude path via stub server

class Stub:
    """Local HTTP server that imitates POST /v1/messages."""

    def __init__(self, body: dict, status: int = 200):
        self.requests: list[tuple[dict, dict]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["content-length"])
                stub.requests.append((dict(self.headers), json.loads(self.rfile.read(length))))
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.client = anthropic.Anthropic(
            api_key="test-key", base_url=f"http://127.0.0.1:{self.server.server_port}", max_retries=0
        )

    def close(self):
        self.server.shutdown()


def message(content, stop_reason="end_turn", model=MODEL):
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": model, "content": content,
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


@pytest.fixture
def stub_factory():
    stubs = []

    def make(body, status=200):
        stubs.append(Stub(body, status))
        return stubs[-1]

    yield make
    for s in stubs:
        s.close()


def test_claude_request_shape_and_answer(stub_factory):
    stub = stub_factory(message([
        {"type": "thinking", "thinking": "...", "signature": "sig"},
        {"type": "text", "text": "The HPA scales on CPU utilisation [1]."},
    ]))
    ans = ClaudeGenerator(client=stub.client, effort="low").answer("How does HPA scale?", CHUNKS)

    headers, body = stub.requests[0]
    assert body["model"] == "claude-opus-5-5"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "low"}
    assert body["fallbacks"] == "default"
    assert FALLBACK_BETA in headers.get("anthropic-beta", "")
    assert "temperature" not in body and body["max_tokens"] == 16000
    assert "[1] (k8s.md › HPA)" in body["messages"][0]["content"]

    assert ans.text == "The HPA scales on CPU utilisation [1]."
    assert ans.cited == {1} and not ans.invalid_citations


def test_claude_fallback_block_is_reported(stub_factory):
    stub = stub_factory(message([
        {"type": "fallback", "from": {"model": MODEL}, "to": {"model": "claude-opus-4-8"},
         "trigger": {"type": "refusal", "category": None}},
        {"type": "text", "text": "A Service gives pods a stable IP [2]."},
    ], model="claude-opus-4-8"))
    ans = ClaudeGenerator(client=stub.client).answer("What is a Service?", CHUNKS)
    assert ans.notes == [f"{MODEL} declined; claude-opus-4-8 answered"]
    assert ans.generator == "claude (claude-opus-4-8)"


def test_claude_refusal_returns_clear_message(stub_factory):
    stub = stub_factory(message([], stop_reason="refusal"))
    ans = ClaudeGenerator(client=stub.client).answer("anything", CHUNKS)
    assert "declined" in ans.text and "refusal" in ans.notes


def test_api_error_falls_back_to_offline_answer(stub_factory):
    stub = stub_factory({"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}, 401)
    ans = ask("What does a Service give to pods?", BM25(CHUNKS), ClaudeGenerator(client=stub.client))
    assert ans.generator == "extractive (offline)"
    assert any("invalid API key" in n for n in ans.notes)


def test_light_stemmer_matches_plural_forms_without_breaking_words():
    from rag.retrieval import stem

    assert stem("attackers") == stem("attacker")
    assert stem("policies") == "policy"
    assert stem("status") == "status" and stem("analysis") == "analysis"
    assert stem("ed25519") == "ed25519"
