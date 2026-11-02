"""The book's thin agent loop: send messages, read one JSON tool call, run it, and stop at an answer or a step limit.

Each reply must be one JSON object, `{"tool": "NAME", "arguments": {...}}`. The loop runs the tool and, if the tool's
result is an `Answer`, stops. Otherwise it sends the result back and asks again, up to `max_steps` model calls; a run
that reaches the limit ends with `Answer.step_limit()`, a failure that `grade()` scores apart from declines. Every
model reply and tool result is kept in a `Trace`, so you can read exactly what happened in a run. Planning, memory and
several agents working together are out of scope: the loop does one data-specific job.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .answers import Answer
from .model import Model
from .tools import Toolbox

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass
class Step:
    kind: str                         # "model" or "tool"
    content: str
    tool: str | None = None
    arguments: dict | None = None


@dataclass
class Trace:
    question: str
    steps: list[Step] = field(default_factory=list)
    answer: Answer | None = None

    def show(self) -> str:
        lines = [f"question: {self.question}"]
        for number, step in enumerate(self.steps, start=1):
            lines.append(f"step {number} ({step.kind}):")
            lines += [f"  {line}" for line in step.content.splitlines()]
        return "\n".join(lines)


def parse_tool_call(reply: str) -> tuple[str, dict]:
    """The tool name and arguments in a reply. Raises ValueError if the reply isn't one JSON tool call."""
    try:
        call = json.loads(FENCE.sub("", reply.strip()))
    except json.JSONDecodeError as e:
        raise ValueError(f"the reply isn't JSON: {e.msg}") from None
    if not isinstance(call, dict) or not isinstance(call.get("tool"), str):
        raise ValueError('the reply needs a "tool" name')
    return call["tool"], call.get("arguments") or {}


def run_agent(question: str, system: str, model: Model, toolbox: Toolbox, max_steps: int = 3) -> Trace:
    """Answer one question: at most `max_steps` model calls, each a tool call. Returns the run's trace."""
    trace = Trace(question)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    for _ in range(max_steps):
        reply = model.complete(messages)
        messages.append({"role": "assistant", "content": reply})
        try:
            name, arguments = parse_tool_call(reply)
        except ValueError as e:
            trace.steps.append(Step("model", reply))
            result_text, answer = f"error: {e}. Reply with one JSON tool call.", None
        else:
            trace.steps.append(Step("model", reply, name, arguments))
            result = toolbox.call(name, arguments)
            result_text, answer = result.content, result.answer
        trace.steps.append(Step("tool", result_text))
        if answer is not None:
            trace.answer = answer
            return trace
        messages.append({"role": "tool", "content": result_text})
    trace.answer = Answer.step_limit(f"no answer within {max_steps} model calls", role=toolbox.role)
    return trace
