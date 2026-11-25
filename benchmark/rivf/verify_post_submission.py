"""Offline verification of post-submission analyses (tierA, tierB, tierC) and probe set.

Standard library only; no network calls or external packages required.
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS = ROOT / "post_submission"
TB = PS / "tierB"
TC = PS / "tierC"


def run_py(args: list[str]) -> None:
    r = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Command failed ({args}):\n{r.stdout}\n{r.stderr}")


def main() -> int:
    # 1. Probe set hash & rules
    r = subprocess.run(
        [sys.executable, "benchmark/rivf/build_probe_set.py", "--verify"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if r.returncode != 0 or "7f6b97e512d31a77aab6f22b1eeb6d84700f66e08a4068a5bdab357d5c3fddc9" not in r.stdout:
        raise RuntimeError(f"Probe set verification failed:\n{r.stdout}\n{r.stderr}")

    # 2. Question-authoring provenance
    pprov = json.loads((ROOT / "benchmark/rivf/probe_authoring_provenance_v1.json").read_text(encoding="utf-8"))
    assert pprov["authoring_model_id"] == "claude-opus-5"
    assert pprov["auditor_model_id"] == "claude-opus-5"
    assert pprov["authoring_agents"] == 13 and pprov["auditor_agents"] == 3

    # 3. Tier-B judge provenance
    jprov = json.loads((TB / "judge_provenance.json").read_text(encoding="utf-8"))
    w1 = jprov["workflows"]["tier_b_primary"]
    assert w1["real_answer_pairs_same_model"] == 218 and w1["real_answers_total"] == 268
    assert w1["breakdown"]["passA_claims"]["models_batches"] == {"claude-fable-5-1": 20}
    assert w1["breakdown"]["passB_claims"]["models_batches"] == {"claude-opus-5-5": 20}

    # 4. Cross-model stats & Tier-C span-on-page summary (--check)
    run_py([str(TB / "crossmodel_stats.py"), str(TB), str(ROOT), "--check"])
    run_py([str(TC / "verify_claims_on_pages.py"), str(TC), str(TB), str(ROOT), "--check"])

    # 5. Recompute deref_stats, judge_stats, and stratify_v4 in a temp copy and compare JSON outputs
    with tempfile.TemporaryDirectory() as tmp:
        tdir = Path(tmp) / "tierB"
        shutil.copytree(TB, tdir)
        run_py([str(tdir / "deref_stats.py"), str(tdir)])
        run_py([str(tdir / "judge_stats.py"), str(tdir), str(ROOT)])
        run_py([str(tdir / "stratify_v4.py"), str(ROOT), str(tdir)])
        for fn in ("deref_stats.json", "judge_stats.json", "stratify_v4.json"):
            got = json.loads((tdir / fn).read_text(encoding="utf-8"))
            exp = json.loads((TB / fn).read_text(encoding="utf-8"))
            if got != exp:
                raise RuntimeError(f"Mismatch recomputing {fn}")

    print("PASS post-submission analyses: probe provenance, deref_stats, judge_stats, crossmodel_stats, stratify_v4, and recovery summary verified.")
    return 0


import shutil
if __name__ == "__main__":
    raise SystemExit(main())
