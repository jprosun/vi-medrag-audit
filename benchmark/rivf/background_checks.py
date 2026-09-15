"""Check contextual corpus/extraction figures from published per-article records.

These are aggregation checks. Repeating extraction or verifying spans needs original text.
"""
from pathlib import Path
import json
import math
ROOT=Path(__file__).resolve().parents[2]
def read(path):
    return json.loads((ROOT/path).read_text(encoding="utf-8"))
def require(ok,message):
    if not ok: raise ValueError(message)
def main():
    reports={}
    for version,expected in (("v1",86/150),("v2",140/150),("v3_canonical",141/150)):
        d=read(f"benchmark/g2/g2_full_report_{version}.json")
        rows=d["per_article"]; require(len(rows)==150,"article denominator")
        require(len({r["article_id"] for r in rows})==150,"duplicate article IDs")
        for field,record in d["per_field"].items():
            count=sum(next(f["verified_fill"] for f in row["fields"] if f["field"]==field)
                      for row in rows)
            require(math.isclose(count/150,record["verified_fill"]),f"{version} {field}")
        count=sum(any(f["verified_fill"] for f in row["fields"]
                      if f["field"] in ("n","primary_numeric_finding")) for row in rows)
        require(math.isclose(count/150,expected),f"{version} numeric extraction")
        require(math.isclose(count/150,d["gate"]["verified_fill_n_or_primary_numeric"]),f"{version} gate")
        reports[version]=d
    require({r["article_id"] for r in reports["v1"]["per_article"]}==
            {r["article_id"] for r in reports["v2"]["per_article"]},"v1/v2 sample changed")
    rows=reports["v3_canonical"]["per_article"]
    vn=[r for r in rows if not r["stratum"].startswith("en_ref")]
    en=[r for r in rows if r["stratum"].startswith("en_ref")]
    require((len(vn),len(en))==(145,5),"language strata")
    counts=[sum(next(f["verified_fill"] for f in r["fields"] if f["field"]==field) for r in vn)
            for field in reports["v3_canonical"]["per_field"]]
    require((min(counts),max(counts))==(136,139),"Vietnamese field counts")
    require(not any(f["verified_fill"] for r in en for f in r["fields"]),"English field count")
    require(sum(r["model_says_scrambled"] for r in rows)==116,"unvalidated scrambled flag count")
    base="docs/project/vmj-dedup/"
    dup=read(base+"duplication_audit.json")["result"]
    require((dup["total_chunks"],dup["distinct_texts"],dup["dup_lines"])==(162681,132225,60906),"export duplication")
    require(round(100*dup["dup_lines"]/dup["total_chunks"],1)==37.4,"duplicate-member share")
    before=read(base+"replace-run2/replace_census_latest.json")
    after=read(base+"replace-run2/replace_verify_latest.json")
    require((before["exact_source_points"],after["exact_source_points"])==(152275,132225),"live replacement counts")
    require(before["exact_non_source_points"]==after["exact_non_source_points"],"other strata changed")
    require(after["exact_total"]==595663,"final collection size")
    require(after["sampled_points"]==32 and after["failed"]==["sampled_text_is_clean"],"residual defect disclosure")
    print("PASS supporting corpus figures: extraction 0.573/0.933/0.940; VN fields 136-139/145; EN 0/5.")
    print("PASS duplication: 60906/162681 export rows belong to duplicate groups; live points 152275 -> 132225.")
    print("NOTE scrambled flags are model outputs, not a validated ingestion-quality measure.")
    return 0
if __name__=="__main__":
    raise SystemExit(main())
