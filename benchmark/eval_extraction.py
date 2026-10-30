"""Phase 6 - Extraction quality.

* Recall against Wikidata (structured ground truth crawled in phase 1): founders, CEOs, headquarters,
  parent / owner organisations. Reported on all facts and on facts whose object is mentioned in the text.
* Precision: an LLM judge checks whether a random sample of extracted relations is supported by the
  evidence sentence stored with the relation (provenance).
"""
import json
import random

from rapidfuzz import fuzz

from common import config, llm
from common.entity_resolution import norm_key
from common.stores import hdfs_read_jsonl, log_run, run_cypher

# wikidata relation -> list of (graph relation, reversed?) ; reversed = graph edge goes object -> subject
GRAPH_EQUIV = {
    "FOUNDED": [("FOUNDED", True)],
    "CEO_OF": [("CEO_OF", True)],
    "HEADQUARTERED_IN": [("HEADQUARTERED_IN", False)],
    "SUBSIDIARY_OF": [("SUBSIDIARY_OF", False), ("ACQUIRED", True), ("OWNS", True)],
    "OWNED_BY": [("SUBSIDIARY_OF", False), ("ACQUIRED", True), ("OWNS", True)],
}


def same(a, names):
    ka = norm_key(a)
    return any(fuzz.token_set_ratio(ka, norm_key(n)) >= 90 for n in names)


def wikidata_recall():
    facts = hdfs_read_jsonl(f"{config.HDFS_RAW}/wikidata/facts.jsonl")
    docs = {d["wikidata_id"]: d["text"].lower() for d in hdfs_read_jsonl(f"{config.HDFS_RAW}/wikipedia/docs.jsonl")}
    edges = run_cypher("""MATCH (a:Entity)-[r]->(b:Entity)
                          WHERE type(r) IN ['FOUNDED','CEO_OF','HEADQUARTERED_IN','SUBSIDIARY_OF','ACQUIRED','OWNS']
                          RETURN type(r) AS rel, a.aliases + [a.name] AS a, b.aliases + [b.name] AS b""")
    by_rel = {}
    for e in edges:
        by_rel.setdefault(e["rel"], []).append(e)

    per_rel, rows = {}, []
    for f in facts:
        if f["object"].startswith("Q") and f["object"][1:].isdigit():
            continue  # unlabeled wikidata item
        found = False
        for grel, rev in GRAPH_EQUIV[f["relation"]]:
            src, tgt = (f["object"], f["subject"]) if rev else (f["subject"], f["object"])
            if any(same(src, e["a"]) and same(tgt, e["b"]) for e in by_rel.get(grel, [])):
                found = True
                break
        in_text = norm_key(f["object"]) in norm_key(docs.get(f["qid"], ""))
        st = per_rel.setdefault(f["relation"], {"facts": 0, "found": 0, "in_text": 0, "found_in_text": 0})
        st["facts"] += 1; st["found"] += found; st["in_text"] += in_text; st["found_in_text"] += found and in_text
        rows.append({**f, "found": found, "in_text": in_text})
    total = {k: sum(v[k] for v in per_rel.values()) for k in ("facts", "found", "in_text", "found_in_text")}
    for st in list(per_rel.values()) + [total]:
        st["recall_all"] = round(st["found"] / max(1, st["facts"]), 3)
        st["recall_in_text"] = round(st["found_in_text"] / max(1, st["in_text"]), 3)
    return {"per_relation": per_rel, "total": total}, rows


JUDGE_SCHEMA = {"type": "OBJECT", "properties": {"verdicts": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "id": {"type": "INTEGER"}, "supported": {"type": "BOOLEAN"}, "reason": {"type": "STRING"}},
    "required": ["id", "supported"]}}}, "required": ["verdicts"]}


def judged_precision(sample_size=60, seed=42):
    rels = run_cypher("""MATCH (a:Entity)-[r]->(b:Entity) WHERE type(r) <> 'MENTIONED_IN' AND size(r.evidence) > 0
                         RETURN a.name AS source, type(r) AS relation, b.name AS target, r.evidence[0] AS evidence""")
    random.Random(seed).shuffle(rels)
    sample = rels[:sample_size]
    verdicts = {}
    for i in range(0, len(sample), 15):
        batch = sample[i:i + 15]
        lines = "\n".join(f'{i + j}. ({r["source"]}) -[{r["relation"]}]-> ({r["target"]}) | evidence: "{r["evidence"]}"'
                          for j, r in enumerate(batch))
        res = llm.generate(f"""You audit a knowledge graph. For each numbered triple, decide whether the evidence
sentence fully supports the triple, including the relation direction. Relation meanings:
{json.dumps({k: v[2] for k, v in config.RELATION_TYPES.items()})}

{lines}""", schema=JUDGE_SCHEMA)
        for v in (res["data"] or {}).get("verdicts", []):
            verdicts[v["id"]] = v
    judged = [{**r, "supported": verdicts.get(i, {}).get("supported"), "reason": verdicts.get(i, {}).get("reason")}
              for i, r in enumerate(sample)]
    ok = [j for j in judged if j["supported"] is not None]
    per_rel = {}
    for j in ok:
        p = per_rel.setdefault(j["relation"], [0, 0]); p[0] += j["supported"]; p[1] += 1
    return {"sample": len(ok), "precision": round(sum(j["supported"] for j in ok) / max(1, len(ok)), 3),
            "per_relation": {k: round(a / b, 3) for k, (a, b) in per_rel.items()}}, judged


def main():
    recall, recall_rows = wikidata_recall()
    precision, judged = judged_precision()
    out = {"wikidata_recall": recall, "judged_precision": precision}
    (config.REPORTS / "extraction_eval.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (config.REPORTS / "extraction_eval_rows.json").write_text(
        json.dumps({"recall": recall_rows, "precision": judged}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2))
    log_run("06_eval_extraction", recall_all=recall["total"]["recall_all"],
            recall_in_text=recall["total"]["recall_in_text"], precision=precision["precision"])


if __name__ == "__main__":
    main()
