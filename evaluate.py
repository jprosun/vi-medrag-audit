"""Reproduce the paper's public offline evaluation (Python 3.10+)."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
CAP = "benchmark/datasets/test_results/pilot_span_exposure_urlfirst_2026-09-07_035612_raw.jsonl"
CHECKS = [
 ("Background corpus/extraction aggregates", ["benchmark/rivf/background_checks.py"]),
 ("Paper numbers", ["paper/check_numbers.py"]),
 ("Shipped entailment", ["benchmark/rivf/entailment_report.py", "--check"]),
 ("URL-first entailment", ["benchmark/rivf/entailment_report.py", "--tag", "urlfirst", "--check"]),
 ("Shipped relevance", ["benchmark/rivf/relevance_report.py", "--check"]),
 ("URL-first relevance", ["benchmark/rivf/relevance_report.py", "--tag", "urlfirst", "--check"]),
 ("Matched paired-question comparison", ["benchmark/rivf/compare_arms_matched.py", "--check"]),
 ("Joint labels and answer coverage", ["benchmark/rivf/joint_support_relevance.py", "--check"]),
 ("Claim retention and retrieval", ["benchmark/rivf/compare_arms.py", "--url-first", CAP, "--check"]),
 ("Human entailment", ["benchmark/rivf/score_human_entailment.py", "--check"]),
 ("Human shipped relevance", ["benchmark/rivf/score_human_relevance.py", "--check"]),
 ("Human URL-first: original and matched", ["benchmark/rivf/score_urlfirst_relevance.py", "--check"]),
 ("Human page-type calibration", ["benchmark/rivf/score_page_type.py", "--check"]),
 ("Confirmatory URL estimate", ["benchmark/rivf/url_confirmatory_estimate.py", "--check"]),
 ("Recorded run configuration", ["benchmark/rivf/run_configuration.py", "--check"]),
 ("Judge sensitivity", ["benchmark/rivf/compare_judge_runs.py", "--check"]),
 ("Probe set integrity", ["benchmark/rivf/build_probe_set.py", "--verify"]),
 ("Post-submission analyses (tierA/B/C)", ["benchmark/rivf/verify_post_submission.py"]),
 ("Submission PDF", ["paper/check_pdf.py"]),
]
def verify_manifest():
    manifest=json.loads((ROOT/"MANIFEST.json").read_text(encoding="utf-8"))
    seen=set()
    for row in manifest["files"]:
        name=row["path"]; path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or name in seen:
            raise ValueError(f"Invalid/duplicate manifest path: {name}")
        seen.add(name)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row["sha256"]:
            raise ValueError(f"File changed since release: {name}")
    return len(seen)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    args=parser.parse_args()
    try:
        print(f"PASS manifest: {verify_manifest()} files")
    except (OSError,ValueError,KeyError) as exc:
        print(f"FAIL manifest: {exc}"); return 1
    checks=list(CHECKS)
    bad=[]
    for name,argv in checks:
        r=subprocess.run([sys.executable,*argv],cwd=ROOT,capture_output=True,text=True,
                         encoding="utf-8",errors="replace",timeout=180)
        print(f"{'PASS' if r.returncode==0 else 'FAIL'} {name}",flush=True)
        if r.returncode:
            bad.append(name); print((r.stdout+"\n"+r.stderr).strip()[-2500:])
    print("NOT RUN: span/numeric verification against original text; source passages are withheld.")
    print(f"{len(checks)-len(bad)}/{len(checks)} public checks passed.")
    return int(bool(bad))
if __name__=="__main__":
    raise SystemExit(main())
