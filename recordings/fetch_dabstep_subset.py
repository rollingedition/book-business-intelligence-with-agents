"""Fetch the small DABstep subset chapter 3 uses, pinned by revision, into examples/data/dabstep/.

DABstep (Data Agent Benchmark for Multi-step Reasoning) is published on Hugging Face under CC BY 4.0. Its repository
takes new leaderboard uploads often, so this script reads one pinned revision and checks every file's SHA-256 before
using it. It takes:

- `data/tasks/dev.jsonl`, keeping only the three easy tasks (5, 49 and 70), as `tasks.jsonl`, unchanged otherwise.
  The ten dev tasks are the only ones with public answers; the seven hard ones need the fee files, not SQL.
- `data/context/payments.csv`, every row, without the four identifier columns (`ip_address`, `email_address`,
  `card_number`, `card_bin`, hashed or partial identifiers no task here needs), gzip-compressed as `payments.csv.gz`.
- `LICENSE`, the dataset's own licence notice, byte for byte.

It reads the network, so it lives in recordings/, never in examples/ (W-48). Run it once:

    python recordings/fetch_dabstep_subset.py

`examples/data/dabstep/SOURCE.md` records the source, the revision, the hashes and every change.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import ssl
import urllib.request
from pathlib import Path

REPO = "adyen/DABstep"
REVISION = "1d740a52b8a41ba6fdd4d4435120a0429023dd24"
SOURCES = {
    "data/tasks/dev.jsonl": "c1da755a6fe9cb538fc84719f51e1db0bff0190a1d6905767ac18c755e66a07b",
    "data/context/payments.csv": "5fbb26210a45427d7a6560cfab3a362a08e4067f27cd03695f211a51c47ffc25",
    "LICENSE": "f8a83b510da6dfffb2fab959cb8a48f05dec344e76338cff7cd5da36b50eec22",
}
TASK_IDS = {"5", "49", "70"}
DROPPED_COLUMNS = ("ip_address", "email_address", "card_number", "card_bin")
TARGET = Path(__file__).resolve().parent.parent / "examples" / "data" / "dabstep"


def download(path: str) -> bytes:
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{path}"
    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE"))
    with urllib.request.urlopen(url, context=context) as response:
        data = response.read()
    found = hashlib.sha256(data).hexdigest()
    if found != SOURCES[path]:
        raise RuntimeError(f"{path}: SHA-256 {found} doesn't match the pinned {SOURCES[path]}")
    return data


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET / "LICENSE").write_bytes(download("LICENSE"))
    tasks = [line for line in download("data/tasks/dev.jsonl").decode("utf-8").splitlines()
             if line.strip() and str(json.loads(line)["task_id"]) in TASK_IDS]
    (TARGET / "tasks.jsonl").write_text("\n".join(tasks) + "\n", encoding="utf-8")

    reader = csv.reader(io.StringIO(download("data/context/payments.csv").decode("utf-8"), newline=""))
    header = next(reader)
    keep = [i for i, name in enumerate(header) if name not in DROPPED_COLUMNS]
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    rows = 0
    writer.writerow([header[i] for i in keep])
    for row in reader:
        writer.writerow([row[i] for i in keep])
        rows += 1
    # mtime=0 and no file name in the header, so the same input always gives the same bytes.
    with open(TARGET / "payments.csv.gz", "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0,
                                                                       filename="") as f:
        f.write(out.getvalue().encode("utf-8"))

    for name in ("LICENSE", "tasks.jsonl", "payments.csv.gz"):
        digest = hashlib.sha256((TARGET / name).read_bytes()).hexdigest()
        print(f"{name}: {(TARGET / name).stat().st_size:,} bytes, sha256 {digest}")
    print(f"tasks: {len(tasks)}; payments rows: {rows:,}; columns: {len(keep)}")


if __name__ == "__main__":
    main()
