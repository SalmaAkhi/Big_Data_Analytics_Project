"""Phase 2a - LLM-based information extraction.

Reads raw documents from HDFS, splits them into chunks and asks Gemini to extract entities and
relationships that follow the shared schema (common/config.py). Results go back to HDFS.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from common import config, llm
from common.stores import hdfs_client, hdfs_read_jsonl, hdfs_write_jsonl, log_run

CHUNK_CHARS = 4500

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "entities": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name": {"type": "STRING"},
            "type": {"type": "STRING", "enum": config.ENTITY_TYPES},
            "description": {"type": "STRING"},
        }, "required": ["name", "type", "description"]}},
        "relations": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "source": {"type": "STRING"},
            "relation": {"type": "STRING", "enum": list(config.RELATION_TYPES)},
            "target": {"type": "STRING"},
            "evidence": {"type": "STRING"},
        }, "required": ["source", "relation", "target", "evidence"]}},
    },
    "required": ["entities", "relations"],
}

SYSTEM = "You are a precise information-extraction system that builds a knowledge graph about the technology industry."


def build_prompt(doc, chunk):
    rels = "\n".join(f"- {r}: ({s}) -> ({t}) : {m}" for r, (s, t, m) in config.RELATION_TYPES.items())
    return f"""Extract entities and relationships from the document below.

Entity types: {", ".join(config.ENTITY_TYPES)}.
Relation types (direction matters, source -> target):
{rels}

Rules:
- Only extract facts explicitly stated in the text. Do not use outside knowledge.
- Use the most complete common name for each entity (e.g. "Mark Zuckerberg", not "Zuckerberg").
- Every relation's source and target must also appear in the entities list.
- "evidence" is the short sentence (max 30 words) from the text that supports the relation.
- description: one short sentence describing the entity based on the text.
- Prefer specific relation types; use RELATED_TO only when nothing else fits.

Document title: {doc["title"]}
Document source: {doc["source"]}
---
{chunk}
---"""


def chunk_text(text, size=CHUNK_CHARS):
    paras, chunks, cur = text.split("\n"), [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            chunks.append(cur)
            cur = ""
        cur += p + "\n"
    if cur.strip():
        chunks.append(cur)
    return chunks


def extract(task):
    doc, idx, chunk = task
    try:
        res = llm.generate(build_prompt(doc, chunk), system=SYSTEM, schema=SCHEMA)
        data = res["data"] or {"entities": [], "relations": []}
        err = None
    except Exception as e:
        res, data, err = {"model": None, "input_tokens": 0, "output_tokens": 0, "latency_s": 0, "cached": False}, \
            {"entities": [], "relations": []}, str(e)[:300]
    print(f"{doc['doc_id']}#{idx}: {len(data['entities'])} entities, {len(data['relations'])} relations"
          f"{' (cache)' if res.get('cached') else ''}{' ERROR ' + err if err else ''}")
    return {
        "doc_id": doc["doc_id"], "chunk_id": f"{doc['doc_id']}#{idx}", "source": doc["source"],
        "title": doc["title"], "url": doc["url"],
        "entities": data.get("entities", []), "relations": data.get("relations", []),
        "model": res["model"], "input_tokens": res["input_tokens"], "output_tokens": res["output_tokens"],
        "latency_s": res["latency_s"], "error": err,
    }


def main():
    t0 = time.time()
    client = hdfs_client()
    docs = []
    for sub in client.list(config.HDFS_RAW):
        if sub != "wikidata":
            docs += hdfs_read_jsonl(f"{config.HDFS_RAW}/{sub}/docs.jsonl")
    tasks = [(d, i, c) for d in docs for i, c in enumerate(chunk_text(d["text"]))]
    print(f"{len(docs)} documents -> {len(tasks)} chunks")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(extract, tasks))

    hdfs_write_jsonl(f"{config.HDFS_EXTRACTED}/extractions.jsonl", results)
    hdfs_write_jsonl(f"{config.HDFS_EXTRACTED}/documents.jsonl",
                     [{k: d.get(k) for k in ("doc_id", "source", "title", "url")} for d in docs])
    it, ot = sum(r["input_tokens"] for r in results), sum(r["output_tokens"] for r in results)
    log_run("02_extract", documents=len(docs), chunks=len(tasks),
            errors=sum(1 for r in results if r["error"]),
            raw_entities=sum(len(r["entities"]) for r in results),
            raw_relations=sum(len(r["relations"]) for r in results),
            input_tokens=it, output_tokens=ot, est_cost_usd=round(llm.cost_usd(it, ot), 4),
            seconds=round(time.time() - t0, 1))


if __name__ == "__main__":
    main()
