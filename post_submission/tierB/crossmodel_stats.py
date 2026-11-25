"""Cross-model answer agreement (Sonnet pass C vs the original passes A, B and the final labels)
and same-specialty sibling controls (Sonnet and Opus).

Usage:
    python -I -X utf8 crossmodel_stats.py <tierB dir> <repo dir> [--check]
Reads judge_result.json, crossmodel_labels.json, key_answers.json, key_siblings.json,
and <repo dir>/benchmark/datasets/probe_queries_v2.jsonl.
"""
import collections
import json
import sys
from pathlib import Path

check_mode = "--check" in sys.argv
args = [a for a in sys.argv[1:] if a != "--check"]
B = Path(args[0])
R = Path(args[1])

res = json.loads((B / "judge_result.json").read_text(encoding="utf-8"))
FIN, PA, PB = res["final"], res["passA"], res["passB"]
keyA = {k["item_id"]: k for k in json.loads((B / "key_answers.json").read_text(encoding="utf-8"))}
keyS = {k["item_id"]: k for k in json.loads((B / "key_siblings.json").read_text(encoding="utf-8"))}
cm = json.loads((B / "crossmodel_labels.json").read_text(encoding="utf-8"))
C = {k: v["label"] for k, v in cm["sonnet_passC"].items()}
O = {k: v["label"] for k, v in cm["opus_siblings"].items()}

LABELS = ("relevant", "partial", "not_relevant")


def kappa(pairs):
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca = collections.Counter(a for a, _ in pairs)
    cb = collections.Counter(b for _, b in pairs)
    pe = sum(ca[l] * cb[l] for l in LABELS) / n / n
    return round((po - pe) / (1 - pe), 4) if pe < 1 else 1.0, round(po, 4)


out = {"n_sonnet_labels": len(C), "n_opus_sibling_labels": len(O)}
real = [i for i, k in keyA.items() if k["kind"] == "real"]
ctrl = [i for i, k in keyA.items() if k["kind"] != "real"]
missing = [i for i in list(keyA) if i not in C]
out["answers_missing_sonnet"] = missing
for name, ref in (("final", FIN), ("passA", PA), ("passB", PB)):
    pr = [(C[i], ref[i]["label"]) for i in real if i in C and i in ref]
    k, po = kappa(pr)
    out[f"kappa_sonnet_vs_{name}_real"] = {"n": len(pr), "kappa": k, "agree": po}

pr = [(C[i] == "relevant", FIN[i]["label"] == "relevant") for i in real if i in C]
out["binary_relevant_agree_vs_final"] = round(sum(a == b for a, b in pr) / len(pr), 4)
out["confusion_sonnet_x_final"] = {
    f"{a}|{b}": v for (a, b), v in collections.Counter((C[i], FIN[i]["label"]) for i in real if i in C).items()
}
out["controls_sonnet"] = dict(collections.Counter(C.get(i) for i in ctrl))

probe = {}
for l in (R / "benchmark/datasets/probe_queries_v2.jsonl").read_text(encoding="utf-8").splitlines():
    if l.strip():
        q = json.loads(l)
        probe[q["query_id"]] = q["source"]

for arm in ("shipped", "urlfirst"):
    items = [i for i in real if keyA[i]["arm"] == arm and i in C]
    ans = [i for i in items if "out_of_corpus_control" not in probe[keyA[i]["query_id"]]]
    oc = [i for i in items if "out_of_corpus_control" in probe[keyA[i]["query_id"]]]
    out[f"{arm}_sonnet"] = {
        "all": f"{sum(C[i] == 'relevant' for i in items)}/{len(items)}",
        "answerable": f"{sum(C[i] == 'relevant' for i in ans)}/{len(ans)}",
        "answerable_rate": round(sum(C[i] == "relevant" for i in ans) / len(ans), 3),
        "out_of_corpus": f"{sum(C[i] == 'relevant' for i in oc)}/{len(oc)}",
        "final_answerable": f"{sum(FIN[i]['label'] == 'relevant' for i in ans)}/{len(ans)}",
    }

sib = sorted(keyS)
out["siblings"] = {
    "n": len(sib),
    "sonnet": dict(collections.Counter(C.get(i) for i in sib)),
    "opus": dict(collections.Counter(O.get(i) for i in sib)),
    "either_relevant": sum(C.get(i) == "relevant" or O.get(i) == "relevant" for i in sib),
    "agree": sum(C.get(i) == O.get(i) for i in sib),
}

target = B / "crossmodel_stats.json"
if check_mode:
    existing = json.loads(target.read_text(encoding="utf-8"))
    if existing != out:
        raise SystemExit(f"crossmodel_stats mismatch:\nexpected={existing}\nactual={out}")
    print("PASS crossmodel_stats.json")
else:
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
