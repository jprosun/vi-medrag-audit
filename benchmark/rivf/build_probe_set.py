"""Assemble, audit and LOCK the RIVF probe question set.

WHAT THIS IS FOR
================
Every headline number in the paper is a label-free mechanical count over a set of
questions: was a claim's span located, was its source openable, was a figure inside a
verified span. No relevance judgement is ever made, so no gold labels are needed and the
sample size is limited only by compute. That is the whole reason this set can exist at
all in the time available.

It also means there is exactly ONE way this set can bias a result: through its topic mix.
A question phrased like a patient FAQ pulls patient-education chunks, which in this corpus
carry no source URL; a question phrased like a study-result lookup pulls journal articles,
which do. Both are legitimate questions and they move the citability numbers in opposite
directions. So the mix is fixed as a grid in advance, the file is hashed BEFORE any
condition is run, and every headline is reported per stratum as well as pooled.

THE RULES THIS FILE ENFORCES, AND WHY EACH ONE
==============================================
1. **Disjoint from every set the system was tuned on.** ``medqa_topic_gold_v2.jsonl`` is
   dev-only by this project's own rule -- the scoring literals removed during
   decontamination were tuned into those 24 questions -- and ``determinism_queries_v1``
   copies 24 of them verbatim. Overlap is checked on exact text AND on a normalised form,
   because a rephrasing of a tuned question is still a tuned question.
2. **No near-duplicates inside the set**, checked by normalised token overlap, so one
   topic cannot dominate a pooled rate through repetition.
3. **The hash is computed in the same canonical form the gates use**
   (``run_span_exposure.sha256_of_query_set``), so the value printed here is directly
   comparable with the value any harness recomputes from the shipped file.
4. **Authoring provenance is recorded per row**, including the audit verdict that let a
   row through. A question set whose origin is "we wrote some questions" cannot be
   defended; one that names its grid cell, its author agent and its audits can.

WHAT IT DOES NOT CLAIM
======================
The questions are author-generated, not drawn from a public benchmark. That is a stated
limitation, not a hidden one: it is why the grid is pre-registered, why the file is
published with the paper, and why no headline is quoted without its per-stratum
breakdown. The mitigation for "the authors chose the questions" is that the choice was
made and hashed before any result was seen, and that the paired comparisons (C0 vs C3 on
identical generations) cannot be moved by question choice at all -- only the absolute
levels can.

Run:
    python benchmark/rivf/build_probe_set.py --draft <workflow-output.json>
    python benchmark/rivf/build_probe_set.py --verify        # re-check the shipped file

Writes ``benchmark/datasets/probe_queries_v2.jsonl`` (the 4-key row shape the runners
read) and ``benchmark/rivf/probe_queries_v2_manifest.json``. Exit 0 on success, 2 on a
rule violation -- a violation must be fixed, never waived.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_JSONL = REPO_ROOT / "benchmark/datasets/probe_queries_v2.jsonl"
OUT_README = REPO_ROOT / "benchmark/datasets/probe_queries_v2_README.md"
MANIFEST = REPO_ROOT / "benchmark/rivf/probe_queries_v2_manifest.json"
TUNED_SETS = [
    REPO_ROOT / "benchmark/datasets/medqa_topic_gold_v2.jsonl",
    REPO_ROOT / "benchmark/datasets/determinism_queries_v1.jsonl",
]
NEAR_DUPLICATE_JACCARD = 0.72
MIN_QUESTION_CHARS = 20


def normalise(text: str) -> str:
    """NFC, lowercase, punctuation to space, whitespace collapsed. Diacritics KEPT.

    Same reasoning as ``app/span_norm``: two Vietnamese words can differ by tone alone,
    so folding tone marks here would report distinct questions as duplicates.
    """
    t = unicodedata.normalize("NFC", text or "").lower()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def tokens(text: str) -> set:
    return set(normalise(text).split())


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def sha256_of_query_set(rows) -> str:
    """Byte-for-byte the form run_gate_g0 / check_determinism / run_span_exposure use."""
    payload = sorted(
        ({"query_id": str(r["query_id"]), "question": str(r["question"])} for r in rows),
        key=lambda item: item["query_id"],
    )
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def check(rows: list) -> list:
    """Every rule, as (severity, message). A 'block' entry means the file may not ship."""
    problems = []

    ids = [r["query_id"] for r in rows]
    if len(set(ids)) != len(ids):
        dupes = [i for i, n in Counter(ids).items() if n > 1]
        problems.append(("block", f"duplicate query_id: {dupes}"))

    for r in rows:
        q = r["question"]
        if len(q.strip()) < MIN_QUESTION_CHARS:
            problems.append(("block", f"{r['query_id']}: question too short to be a question"))
        if q != q.strip():
            problems.append(("block", f"{r['query_id']}: leading/trailing whitespace"))
        if not re.search(r"[À-ỹ]", q):
            # Vietnamese without a single diacritic is either English or mangled.
            problems.append(("warn", f"{r['query_id']}: no Vietnamese diacritic in the question"))

    # Rule 1 — disjoint from the tuned sets.
    tuned = []
    for path in TUNED_SETS:
        for row in load_jsonl(path):
            if row.get("question"):
                tuned.append((path.name, row.get("query_id"), row["question"]))
    tuned_norm = {normalise(q): (f, i) for f, i, q in tuned}
    for r in rows:
        hit = tuned_norm.get(normalise(r["question"]))
        if hit:
            problems.append(("block", f"{r['query_id']}: identical to {hit[0]}:{hit[1]} after normalisation"))
    tuned_tokens = [(f, i, tokens(q)) for f, i, q in tuned]
    for r in rows:
        rt = tokens(r["question"])
        for f, i, tt in tuned_tokens:
            if jaccard(rt, tt) >= NEAR_DUPLICATE_JACCARD:
                problems.append(("block", f"{r['query_id']}: near-duplicate of tuned {f}:{i}"))

    # Rule 2 — no near-duplicates inside the set.
    toks = [(r["query_id"], tokens(r["question"])) for r in rows]
    for a in range(len(toks)):
        for b in range(a + 1, len(toks)):
            j = jaccard(toks[a][1], toks[b][1])
            if j >= NEAR_DUPLICATE_JACCARD:
                problems.append(("block", f"near-duplicate pair {toks[a][0]} / {toks[b][0]} (jaccard {j:.2f})"))

    return problems


def cell(row: dict) -> tuple:
    """(specialty, question_type) for a row, from whichever shape it is in.

    Output rows carry the grid cell inside ``source`` (``rivf_grid_v2:<spec>/<type>``);
    draft rows carry it as two fields. Reading only the draft shape made the shipped
    file report '?' for all 134 rows -- a summary that cannot see its own subject.
    """
    if row.get("specialty"):
        return row.get("specialty", "?"), row.get("question_type", "?")
    src = str(row.get("source", ""))
    if ":" in src and "/" in src:
        tail = src.split(":", 1)[1]
        return tail.split("/", 1)[0], tail.split("/", 1)[1]
    return "?", "?"


def report(rows: list, problems: list) -> int:
    by_specialty = Counter(cell(r)[0] for r in rows)
    by_type = Counter(cell(r)[1] for r in rows)
    digest = sha256_of_query_set(rows)

    print(f"rows            {len(rows)}")
    print(f"specialties     {len(by_specialty)}  {dict(by_specialty)}")
    print(f"question types  {dict(by_type)}")
    print(f"query_set_sha256 {digest}")
    blocking = [m for s, m in problems if s == "block"]
    for sev, msg in problems:
        print(f"  [{sev}] {msg}")
    print("VERDICT:", "BLOCKED" if blocking else "OK")
    return 2 if blocking else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--draft", help="workflow output JSON with {rows, audits}")
    ap.add_argument("--verify", action="store_true", help="re-check the shipped file")
    args = ap.parse_args(argv)

    if args.verify or not args.draft:
        rows = load_jsonl(OUT_JSONL)
        if not rows:
            print(f"nothing to verify: {OUT_JSONL} does not exist", file=sys.stderr)
            return 2
        return report(rows, check(rows))

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    raw = draft["rows"]
    audits = draft.get("audits", [])

    # Apply the audits: must_drop removes, must_edit substitutes, note is recorded only.
    drops, edits, notes, unmatched, superseded = {}, {}, [], [], []
    row_keys = {normalise(q["question"]) for q in raw}
    for a in audits:
        for p in a.get("problems", []):
            key = normalise(p.get("question", ""))
            severity = p.get("severity")
            if severity in ("must_drop", "must_edit") and key not in row_keys:
                # An auditor quoting a question that is not in the set means the quote
                # was paraphrased or truncated, and the directive would otherwise be
                # dropped in silence -- indistinguishable from a clean run.
                unmatched.append({"auditor": a["auditor"], **p})
                continue
            if severity == "must_drop":
                drops[key] = f"{a['auditor']}: {p['problem']}"
            elif severity == "must_edit":
                if not p.get("suggested_replacement"):
                    # A demand to edit with nothing to edit to is unactionable, and
                    # must be seen rather than silently downgraded to a note.
                    unmatched.append({"auditor": a["auditor"], "no_replacement_supplied": True, **p})
                    continue
                if key in edits:
                    # Two auditors want the same question changed. Applying one and
                    # discarding the other without saying so would hide a real finding.
                    superseded.append({"auditor": a["auditor"], **p})
                    continue
                edits[key] = (p["suggested_replacement"].strip(), f"{a['auditor']}: {p['problem']}")
            else:
                notes.append({"auditor": a["auditor"], **p})

    if unmatched:
        print(f"\n{len(unmatched)} audit directive(s) could not be applied:", file=sys.stderr)
        for u in unmatched:
            why = "no replacement supplied" if u.get("no_replacement_supplied") else "quoted question not in the set"
            print(f"  [{u['auditor']}/{u.get('severity')}] {why}: {u.get('question','')[:80]}", file=sys.stderr)
        print("Resolve each one by hand; a probe set may not ship with an audit finding "
              "that was silently discarded.", file=sys.stderr)
        return 2

    rows, dropped = [], []
    for q in raw:
        key = normalise(q["question"])
        if key in drops:
            dropped.append({**q, "dropped_because": drops[key]})
            continue
        edited = edits.get(key)
        row = dict(q)
        if edited:
            row["question"] = edited[0]
            row["edited_because"] = edited[1]
        rows.append(row)

    # Stable ids, ordered by specialty then type, so the file reads as the grid it is.
    rows.sort(key=lambda r: (r.get("specialty", ""), r.get("question_type", ""), r["question"]))
    out = []
    for n, r in enumerate(rows, start=1):
        out.append({
            "query_id": f"rivf_{n:03d}",
            "question": r["question"].strip(),
            "source": f"rivf_grid_v2:{r.get('specialty','?')}/{r.get('question_type','?')}",
            "rationale": (
                f"{r.get('rationale','').strip()} | authored blind from general medical "
                f"knowledge, no corpus access; audited by "
                f"{','.join(a['auditor'] for a in audits)}"
                + (f" | EDITED: {r['edited_because']}" if r.get("edited_because") else "")
            ),
        })

    problems = check(out)
    code = report(out, problems)
    if code != 0:
        print("\nNOT WRITTEN. Fix the blocking problems above; a probe set may not ship with a waiver.", file=sys.stderr)
        return code

    OUT_JSONL.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8"
    )
    MANIFEST.write_text(json.dumps({
        "schema": "rivf_probe_set.v2",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": str(OUT_JSONL.relative_to(REPO_ROOT)).replace("\\", "/"),
        "n": len(out),
        "query_set_sha256": sha256_of_query_set(out),
        "file_sha256": hashlib.sha256(OUT_JSONL.read_bytes()).hexdigest(),
        "by_specialty": dict(Counter(r["source"].split(":")[1].split("/")[0] for r in out)),
        "by_question_type": dict(Counter(r["source"].split("/")[1] for r in out)),
        "authoring": "12 specialty agents + 1 out-of-corpus control agent, each instructed to author blind: no repository access, no web search, no tool use",
        "audits": [{"auditor": a["auditor"], "verdict": a.get("verdict"), "problems": len(a.get("problems", []))} for a in audits],
        "dropped": dropped,
        "edits_applied": [
            {"query_id": r["query_id"], "because": r["rationale"].split("| EDITED: ", 1)[1]}
            for r in out if "| EDITED: " in r["rationale"]
        ],
        "edits_superseded_same_question_flagged_twice": superseded,
        "notes_not_acted_on": notes,
        "rules_enforced": [
            "disjoint from medqa_topic_gold_v2 and determinism_queries_v1, exact and normalised",
            f"no internal near-duplicate pair above jaccard {NEAR_DUPLICATE_JACCARD}",
            "unique query_id, non-empty question, no surrounding whitespace",
        ],
        "lock": "This file is FROZEN. It must not be edited after any condition has been run against it; re-run with --verify to confirm the hash still matches what a result artifact recorded.",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT_JSONL.relative_to(REPO_ROOT)} and {MANIFEST.relative_to(REPO_ROOT)}")
    print("NEXT: commit both, then never edit the jsonl again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
