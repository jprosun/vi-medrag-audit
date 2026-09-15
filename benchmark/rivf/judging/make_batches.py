"""Split a frozen judgement item set into blind batches for a pinned-model re-run.

WHY A RE-RUN. The original judging passes did not pin a model: no agent() call passed one, so
each batch inherited whatever the session was running, and the checkpoint behind the committed
labels is not recoverable from any artifact. That is documented as a limitation in
JUDGE-CONFIGURATION.md and in Section VII. This makes it recoverable going forward, and -- more
useful than the re-run itself -- lets the two label sets be compared, which measures how much
of a headline rate is a property of the judge rather than of the system.

The batching reproduces the original exactly: same item file, same order, same batch size, two
independent passes over the same items. What changes is that the model is named.

    python benchmark/rivf/judging/make_batches.py --instrument entailment
    python benchmark/rivf/judging/make_batches.py --instrument relevance
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUTDIR = REPO / "benchmark/rivf/judging/batches"

SETS = {
    "entailment": REPO / "benchmark/rivf/entailment_items_v1.jsonl",
    "relevance": REPO / "benchmark/rivf/relevance_model_items_v1.jsonl",
}
BATCH = 28  # 222 items -> 8 batches, matching the original run's "8 blind batches each"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", choices=sorted(SETS), required=True)
    a = ap.parse_args()

    src = SETS[a.instrument]
    lines = [l for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    OUTDIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    for pass_name in ("a", "b"):
        for i in range(0, len(lines), BATCH):
            n = i // BATCH + 1
            chunk = lines[i:i + BATCH]
            path = OUTDIR / f"{a.instrument}_{pass_name}{n}.jsonl"
            path.write_text("\n".join(chunk) + "\n", encoding="utf-8")
            manifest.append({
                "pass": pass_name,
                "batch": n,
                "n": len(chunk),
                "path": str(path).replace("\\", "/"),
            })

    (OUTDIR / f"{a.instrument}_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{a.instrument}: {len(lines)} items -> {len(manifest)} batches "
          f"({len(manifest) // 2} per pass), batch size {BATCH}")
    print(f"  source sha256 {hashlib.sha256(src.read_bytes()).hexdigest()[:32]}...")
    print(f"  manifest {(OUTDIR / (a.instrument + '_manifest.json')).relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
