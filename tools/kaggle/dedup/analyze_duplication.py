#!/usr/bin/env python3
"""Audit trung lap text trong chunk export VMJ (buoc truoc khi re-embed).

Tra loi 4 cau hoi thiet ke cua phuong an khua trung lap:
  Q1. Giu-1-bai/title co mat noi dung khong? (partition hay overlap)
  Q2. Cap trung nam o muc nao: cung URL/file/doc hay khac?
  Q3. Id hau to _N va namespace cu la gi?
  Q4. Metadata nao phan duoc ban "tot nhat" de lam keeper?

Xuat ket qua ra JSON de luu vet + dung cho verification ve sau.

Chay:
    py -3.11 tools/kaggle/dedup/analyze_duplication.py \
        --export-dir rag-data/embeddings/exports/vmj_ojs/multilingual \
        --out-json docs/project/vmj-dedup/duplication_audit.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


def norm_title(t: str | None) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


def load_jsonl(path: Path) -> dict:
    data = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                data[rec["id"]] = rec
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", required=True)
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    exp = Path(args.export_dir)
    texts_rec = load_jsonl(exp / "chunk_texts_for_embed.jsonl")
    meta_rec = load_jsonl(exp / "chunk_metadata.jsonl")
    texts = {k: v["text"] for k, v in texts_rec.items()}
    meta = {k: v.get("metadata", {}) for k, v in meta_rec.items()}

    assert set(texts) == set(meta), "id mismatch texts/metadata"

    # ---- Cau truc chung -------------------------------------------------
    art_chunks: dict[str, list[str]] = defaultdict(list)
    art_qmean: dict[str, float] = {}
    for cid, m in meta.items():
        art_chunks[m["article_id"]].append(cid)
    for aid, cids in art_chunks.items():
        art_qmean[aid] = mean(meta[c].get("quality_score") or 0 for c in cids)

    groups: dict[str, list[str]] = defaultdict(list)
    for cid, t in texts.items():
        groups[t].append(cid)
    dup_groups = [ids for ids in groups.values() if len(ids) > 1]
    dup_lines = sum(len(i) for i in dup_groups)

    # ---- Q2: phan loai cap trung ---------------------------------------
    combo = Counter()
    for ids in dup_groups:
        us = {meta[c].get("source_url", "") for c in ids}
        fs = {meta[c].get("source_file", "") for c in ids}
        ds = {meta[c].get("doc_id", "") for c in ids}
        combo[(len(us) > 1, len(fs) > 1, len(ds) > 1)] += 1

    # ---- Title groups ----------------------------------------------------
    title_groups: dict[str, set] = defaultdict(set)
    n_empty_title = 0
    for aid, cids in art_chunks.items():
        t = norm_title(meta[cids[0]].get("canonical_title"))
        if not t:
            n_empty_title += 1
            t = "EMPTY::" + aid
        title_groups[t].add(aid)

    # ---- Q1/Q4: mo phong keeper + do mat noi dung ------------------------
    def pick_keeper(aids):
        return sorted(
            aids,
            key=lambda a: (-len(art_chunks[a]), -art_qmean[a], a),
        )[0]

    lost_texts = []
    kept_arts = set()
    keeper_wins_by_chunks = 0
    for t, aids in title_groups.items():
        keeper = pick_keeper(aids)
        kept_arts.add(keeper)
        kept_texts = {texts[c] for c in art_chunks[keeper]}
        for a in aids:
            if a == keeper:
                continue
            if len(art_chunks[a]) <= len(art_chunks[keeper]):
                keeper_wins_by_chunks += 1
            for c in art_chunks[a]:
                if texts[c] not in kept_texts:
                    lost_texts.append({
                        "title": t[:80],
                        "lost_article_id": a,
                        "keeper_article_id": keeper,
                        "chunk_id": c,
                        "text_preview": texts[c][:120],
                    })

    final_n = sum(len(art_chunks[a]) for a in kept_arts)
    seen, residual = set(), 0
    for a in kept_arts:
        for c in art_chunks[a]:
            if texts[c] in seen:
                residual += 1
            seen.add(texts[c])

    # ---- Q3a: hau to _N ---------------------------------------------------
    suffixed = [c for c in texts if re.search(r"_\d+$", c)]
    base_same = base_diff = base_missing = 0
    for cid in suffixed:
        b = re.sub(r"_\d+$", "", cid)
        if b not in texts:
            base_missing += 1
        elif texts[b] == texts[cid]:
            base_same += 1
        else:
            base_diff += 1

    # ---- Q3b: namespace cu ------------------------------------------------
    old_ns = [c for c in texts if c.startswith("vmj_ojs_")]
    new_set = {texts[c] for c in texts if not c.startswith("vmj_ojs_")}
    old_in_new = sum(1 for c in old_ns if texts[c] in new_set)

    # ---- Doc_id per URL ----------------------------------------------------
    url_docs: dict[str, set] = defaultdict(set)
    for cid, m in meta.items():
        url_docs[m.get("source_url", "")].add(m["doc_id"])

    result = {
        "export_dir": str(exp),
        "total_chunks": len(texts),
        "distinct_texts": len(groups),
        "dup_lines": dup_lines,
        "dup_pct": round(100 * dup_lines / len(texts), 2),
        "dup_groups": len(dup_groups),
        "group_size_hist": dict(Counter(len(i) for i in dup_groups)),
        "pair_classification": {
            f"url_diff={k[0]},file_diff={k[1]},doc_diff={k[2]}": v
            for k, v in sorted(combo.items())
        },
        "articles_total": len(art_chunks),
        "title_groups_multi": sum(1 for s in title_groups.values() if len(s) > 1),
        "articles_in_multi_title": sum(
            len(s) for s in title_groups.values() if len(s) > 1
        ),
        "empty_title_articles": n_empty_title,
        "urls_total": len(url_docs),
        "urls_multi_doc": sum(1 for d in url_docs.values() if len(d) > 1),
        "simulated_dedup": {
            "policy": "keep-1-per-title: max(#chunks) -> max(mean quality_score) -> min(article_id)",
            "kept_articles": len(kept_arts),
            "final_chunks": final_n,
            "removed_chunks": len(texts) - final_n,
            "removed_pct": round(100 * (len(texts) - final_n) / len(texts), 2),
            "content_loss_texts": len(lost_texts),
            "content_loss_pct_of_export": round(100 * len(lost_texts) / len(texts), 3),
            "title_groups_with_loss": len({r["title"] for r in lost_texts}),
            "residual_dup_after_dedup": residual,
            "keeper_beats_or_ties_dropped_on_chunks": keeper_wins_by_chunks,
        },
        "suffix_N_ids": {
            "count": len(suffixed),
            "same_text_as_base": base_same,
            "diff_text_from_base": base_diff,
            "base_not_found": base_missing,
        },
        "old_namespace": {
            "vmj_ojs_prefix_chunks": len(old_ns),
            "found_in_new_namespace": old_in_new,
        },
    }

    out = Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"result": result}
    if lost_texts:
        payload["content_loss_examples"] = lost_texts[:50]
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
