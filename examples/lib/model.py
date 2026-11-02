"""Models, as the examples see them: anything with `complete(messages) -> str`.

Examples never call a model. `RecordedModel("name")` replays the replies a pinned model gave, which the scripts in
`recordings/` saved under `examples/data/recorded/{name}/`. Each reply is stored under the SHA-256 of the exact
messages that produced it, so replay returns the model's real reply to that prompt. A prompt that was never recorded,
including one changed by a single character, raises `MissingRecording` instead of reusing another reply.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .prompts import messages_sha256

RECORDED = Path(__file__).resolve().parent.parent / "data" / "recorded"


class Model(Protocol):
    def complete(self, messages: list[dict]) -> str: ...


class MissingRecording(KeyError):
    """No reply was recorded for these exact messages."""


class RecordedModel:
    """Replays a recording: each call returns the reply recorded for the same messages."""

    def __init__(self, name: str):
        self.name = name
        self.folder = RECORDED / name
        self.manifest = json.loads((self.folder / "manifest.json").read_text(encoding="utf-8"))
        self.calls = {}
        for output in self.manifest["outputs"]:
            for line in (self.folder / output).read_text(encoding="utf-8").splitlines():
                call = json.loads(line)
                self.calls[call["messages_sha256"]] = call

    def complete(self, messages: list[dict]) -> str:
        return self.call_for(messages)["reply"]

    def call_for(self, messages: list[dict]) -> dict:
        """The whole recorded call for these messages: its reply, question ID, seconds and token counts."""
        key = messages_sha256(messages)
        if key not in self.calls:
            raise MissingRecording(f"{self.name}: no reply recorded for messages {key[:12]}; record them again")
        return self.calls[key]


class RecordedModels:
    """Replays several recordings as one: each call returns the reply from the first recording that holds it.

    Chapter 7 uses it for runs whose first call an earlier chapter recorded, and whose repair call it recorded itself.
    """

    def __init__(self, *names: str):
        self.models = [RecordedModel(name) for name in names]

    def complete(self, messages: list[dict]) -> str:
        return self.call_for(messages)["reply"]

    def call_for(self, messages: list[dict]) -> dict:
        key = messages_sha256(messages)
        for model in self.models:
            if key in model.calls:
                return model.calls[key]
        names = ", ".join(model.name for model in self.models)
        raise MissingRecording(f"{names}: no reply recorded for messages {key[:12]}; record them again")
