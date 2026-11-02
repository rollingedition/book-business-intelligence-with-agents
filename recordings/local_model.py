"""The pinned model every recording in this book uses, run on the CPU with llama-cpp-python.

Model: Qwen3-4B-Instruct-2507 (Qwen, Apache-2.0), quantized to 4 bits (Q4_K_M) in GGUF, pinned to one file by its
repository revision and SHA-256. The file (about 2.5 GB) is downloaded once into a cache outside the repository
(`RE_MODEL_CACHE`, or `~/.cache/rolling-edition/models`) and checked against the hash before every use.

Chat template: the GGUF file embeds a template that differs from the one Qwen publishes for this model (it adds
empty thinking blocks to assistant turns after the last user turn). So prompts are rendered with Qwen's own template,
read from the model's `tokenizer_config.json` at a pinned revision and checked by hash, and the model is given the
rendered text.

Sampling is Qwen's recommendation for this model (temperature 0.7, top-p 0.8, top-k 20, min-p 0), with the seed reset
before every call. Output is capped at `max_tokens` (384 for SQL, 256 otherwise), which is this book's choice.

This module reads the network (to download) and runs a model, so it lives in recordings/, never in examples/.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import ssl
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import jinja2

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "examples"))

from lib.prompts import messages_sha256  # noqa: E402

MODEL = "Qwen3-4B-Instruct-2507"
GGUF_REPO = "unsloth/Qwen3-4B-Instruct-2507-GGUF"
GGUF_REVISION = "a06e946bb6b655725eafa393f4a9745d460374c9"
GGUF_FILE = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
GGUF_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
TEMPLATE_REPO = "Qwen/Qwen3-4B-Instruct-2507"
TEMPLATE_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
TEMPLATE_FILE = "tokenizer_config.json"
TEMPLATE_SHA256 = "a62ff0a2472a0fa1b8eaabcb57c59b58afa42a22831dc141400b6e0cf2b65ce3"

SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0}
SEED = 2718
THREADS = 4
CONTEXT_TOKENS = 8192


def cache_dir() -> Path:
    folder = Path(os.environ.get("RE_MODEL_CACHE", Path.home() / ".cache" / "rolling-edition" / "models"))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(repo: str, revision: str, filename: str, sha256: str) -> Path:
    """A pinned file from Hugging Face, downloaded once into the cache and checked by hash every time."""
    path = cache_dir() / f"{revision[:12]}-{filename}"
    if not path.exists():
        url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
        context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE"))
        partial = path.with_suffix(".part")
        with urllib.request.urlopen(url, context=context) as response, open(partial, "wb") as out:
            while block := response.read(1 << 20):
                out.write(block)
        partial.rename(path)
    found = sha256_of(path)
    if found != sha256:
        raise RuntimeError(f"{filename}: SHA-256 {found} doesn't match the pinned {sha256}; delete it and retry")
    return path


@dataclass
class Reply:
    text: str
    seconds: float
    prompt_tokens: int
    completion_tokens: int


class LocalModel:
    """The pinned model. `complete(messages)` renders Qwen's chat template and samples one reply."""

    def __init__(self, max_tokens: int = 256):
        from llama_cpp import Llama, __version__

        self.max_tokens = max_tokens
        self.runner = f"llama-cpp-python {__version__}"
        config = json.loads(fetch(TEMPLATE_REPO, TEMPLATE_REVISION, TEMPLATE_FILE, TEMPLATE_SHA256).read_text())
        environment = jinja2.Environment(trim_blocks=False, lstrip_blocks=False)
        self.template = environment.from_string(config["chat_template"])
        self.llm = Llama(model_path=str(fetch(GGUF_REPO, GGUF_REVISION, GGUF_FILE, GGUF_SHA256)),
                         n_ctx=CONTEXT_TOKENS, n_threads=THREADS, seed=SEED, verbose=False)
        embedded = self.llm.metadata.get("tokenizer.chat_template", "")
        self.embedded_template_matches = embedded == config["chat_template"]

    def render(self, messages: list[dict]) -> str:
        return self.template.render(messages=messages, add_generation_prompt=True)

    def complete(self, messages: list[dict]) -> Reply:
        prompt = self.render(messages)
        start = time.perf_counter()
        # The seed is reset before every call. The runner reuses the cached prefix the call shares with the last one.
        out = self.llm.create_completion(prompt, max_tokens=self.max_tokens, seed=SEED, stop=["<|im_end|>"],
                                         **SAMPLING)
        seconds = time.perf_counter() - start
        usage = out["usage"]
        return Reply(out["choices"][0]["text"], round(seconds, 1), usage["prompt_tokens"], usage["completion_tokens"])


class Recorder:
    """Wraps the live model for the agent loop: each call is answered by the model and saved as one JSON line."""

    def __init__(self, model: LocalModel, question_id: str, calls: list[dict]):
        self.model, self.question_id, self.calls = model, question_id, calls

    def complete(self, messages: list[dict]) -> str:
        reply = self.model.complete(messages)
        self.calls.append({"question_id": self.question_id, "messages_sha256": messages_sha256(messages),
                           "reply": reply.text, "seconds": reply.seconds, "prompt_tokens": reply.prompt_tokens,
                           "completion_tokens": reply.completion_tokens})
        print(f"{self.question_id}: {reply.seconds} s, {reply.prompt_tokens} prompt tokens", flush=True)
        return reply.text


def recorded_questions(folder: Path, part: int) -> list[dict]:
    """The calls a part already holds. A part records only questions it doesn't have, so earlier replies stay."""
    path = folder / f"part-{part}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def write_part(folder: Path, part: int, calls: list[dict], manifest_fields: dict, model: LocalModel) -> None:
    """Add calls to `part-N.jsonl`, after the ones it holds, and merge the part into the recording's manifest.json."""
    folder.mkdir(parents=True, exist_ok=True)
    output = f"part-{part}.jsonl"
    calls = recorded_questions(folder, part) + calls
    with open(folder / output, "w", encoding="utf-8") as f:
        for call in calls:
            f.write(json.dumps(call, ensure_ascii=False, sort_keys=True) + "\n")
    path = folder / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {}
    parts = {p["output"]: p for p in manifest.get("parts", [])}
    parts[output] = {"output": output, "part": part, "created": date.today().isoformat(), "calls": len(calls),
                     "question_ids": sorted({c["question_id"] for c in calls}),
                     "seconds_per_call": [c["seconds"] for c in calls]}
    parts = sorted(parts.values(), key=lambda p: p["part"])
    manifest.update(manifest_fields)
    manifest.update({
        "model": f"{TEMPLATE_REPO} ({GGUF_REPO}/{GGUF_FILE})",
        "model_version": f"{GGUF_REVISION} sha256:{GGUF_SHA256}",
        "quantization": "Q4_K_M",
        "chat_template": f"{TEMPLATE_REPO}@{TEMPLATE_REVISION} {TEMPLATE_FILE} sha256:{TEMPLATE_SHA256}",
        "embedded_template_matches": model.embedded_template_matches,
        "runner": f"{model.runner} on CPU, {THREADS} threads ({platform.machine()})",
        "sampling": dict(SAMPLING, seed=SEED, max_tokens=model.max_tokens, seed_reset="before every call"),
        "created": max(p["created"] for p in parts),
        "outputs": [p["output"] for p in parts],
        "calls": sum(p["calls"] for p in parts),
        "parts": parts,
    })
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
