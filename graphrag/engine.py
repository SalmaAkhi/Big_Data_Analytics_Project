"""Phase 5 - GraphRAG and Text2Cypher over the shared knowledge graph.

GraphRAG pipeline:
  1. entity linking   : LLM extracts mentions -> full-text lookup  +  vector search on the question
  2. graph retrieval  : 1-2 hop neighbourhood of the seed entities, ranked by PageRank / weight
  3. generation       : the LLM answers only from the retrieved triples and cites document ids

Text2Cypher: the LLM translates the question into a read-only Cypher query that is executed directly.
"""
import re
import time

from common import config, llm
from common.stores import run_cypher

MAX_TRIPLES = 90

LINK_SCHEMA = {"type": "OBJECT", "properties": {"entities": {"type": "ARRAY", "items": {"type": "STRING"}}},
               "required": ["entities"]}
ANSWER_SCHEMA = {"type": "OBJECT", "properties": {
    "answer": {"type": "STRING"},
    "cited_documents": {"type": "ARRAY", "items": {"type": "STRING"}},
    "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
}, "required": ["answer", "cited_documents", "confidence"]}


class Usage:
    def __init__(self):
        self.input_tokens = self.output_tokens = self.llm_calls = 0

    def add(self, res):
        self.input_tokens += res["input_tokens"]
        self.output_tokens += res["output_tokens"]
        self.llm_calls += 1

    def as_dict(self):
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "llm_calls": self.llm_calls,
                "cost_usd": round(llm.cost_usd(self.input_tokens, self.output_tokens), 6)}


def _lucene_escape(s):
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", s)


def link_entities(question, usage, use_cache=True, k_vector=5):
    res = llm.generate(
        f"List the named entities (companies, people, products, places, technologies) mentioned in this question. "
        f"Return them exactly as written.\nQuestion: {question}", schema=LINK_SCHEMA, use_cache=use_cache)
    usage.add(res)
    mentions = (res["data"] or {}).get("entities", [])
    seeds = {}
    for m in mentions:
        rows = run_cypher("""CALL db.index.fulltext.queryNodes('entity_fulltext', $q) YIELD node, score
                             RETURN node.id AS id, node.name AS name, score LIMIT 2""",
                          q=f'"{_lucene_escape(m)}" OR {_lucene_escape(m)}~')
        for r in rows:
            seeds.setdefault(r["id"], {"name": r["name"], "via": f"texte:{m}", "score": r["score"]})
    vec = llm.embed([question], task_type="RETRIEVAL_QUERY")[0]
    for r in run_cypher("""CALL db.index.vector.queryNodes('entity_embedding', $k, $v) YIELD node, score
                           RETURN node.id AS id, node.name AS name, score""", k=k_vector, v=vec):
        if r["score"] > 0.6:
            seeds.setdefault(r["id"], {"name": r["name"], "via": "vecteur", "score": r["score"]})
    return mentions, seeds


def retrieve_subgraph(seed_ids):
    rows = run_cypher("""
        MATCH (s:Entity) WHERE s.id IN $ids
        MATCH p = (s)-[*1..2]-(o:Entity)
        WHERE all(r IN relationships(p) WHERE type(r) <> 'MENTIONED_IN')
        UNWIND relationships(p) AS r
        WITH DISTINCT r, startNode(r) AS a, endNode(r) AS b
        RETURN a.name AS source, a.type AS source_type, type(r) AS relation, b.name AS target,
               b.type AS target_type, r.sources AS sources, r.evidence[0] AS evidence,
               coalesce(a.pagerank, 0) + coalesce(b.pagerank, 0) + r.weight AS rank,
               (a.id IN $ids OR b.id IN $ids) AS direct
        ORDER BY direct DESC, rank DESC LIMIT $limit""", ids=list(seed_ids), limit=MAX_TRIPLES)
    return rows


def format_context(triples):
    lines = []
    for t in triples:
        src = ",".join(t["sources"] or [])
        ev = f' | evidence: "{t["evidence"]}"' if t.get("evidence") else ""
        lines.append(f'({t["source"]}:{t["source_type"]}) -[{t["relation"]}]-> ({t["target"]}:{t["target_type"]})'
                     f' | docs: {src}{ev}')
    return "\n".join(lines)


def graphrag_answer(question, use_cache=True):
    t0 = time.time()
    usage = Usage()
    mentions, seeds = link_entities(question, usage, use_cache)
    triples = retrieve_subgraph(seeds.keys()) if seeds else []
    context = format_context(triples)
    res = llm.generate(f"""Answer the question using ONLY the knowledge-graph facts below.
Each fact is (subject:type) -[RELATION]-> (object:type) followed by the ids of the source documents.
- Combine several facts for multi-hop questions and list all matching entities when asked.
- Cite the document ids that support your answer in cited_documents.
- If the facts are not sufficient, say so clearly instead of guessing.

Facts:
{context or "(no facts retrieved)"}

Question: {question}""", schema=ANSWER_SCHEMA, use_cache=use_cache)
    usage.add(res)
    data = res["data"] or {}
    return {"approach": "GraphRAG", "answer": data.get("answer", res["text"]),
            "cited_documents": data.get("cited_documents", []), "confidence": data.get("confidence"),
            "mentions": mentions, "seeds": seeds, "triples": triples,
            "latency_s": round(time.time() - t0, 3), **usage.as_dict()}


# ------------------------------------------------------------------ Text2Cypher
def graph_schema_text():
    rels = "\n".join(f"(:{s})-[:{r}]->(:{t})  // {m}" for r, (s, t, m) in config.RELATION_TYPES.items())
    return f"""Node label :Entity with properties id, name, type, description, aliases (list), pagerank, community.
Every entity also has one label among: {", ".join(config.ENTITY_TYPES)}.
Relationships (direction matters):
{rels}
(:Entity)-[:MENTIONED_IN]->(:Document {{id, title, url, source}})
Relationship properties: weight (int), sources (list of document ids), evidence (list of strings)."""


CYPHER_SCHEMA = {"type": "OBJECT", "properties": {"cypher": {"type": "STRING"}}, "required": ["cypher"]}
WRITE_CLAUSES = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s+apoc\.(?!text))\b", re.I)


def text2cypher_answer(question, use_cache=True):
    t0 = time.time()
    usage = Usage()
    res = llm.generate(f"""Write one read-only Cypher query for Neo4j 5 that answers the question.
Schema:
{graph_schema_text()}
Rules: match names case-insensitively with toLower(n.name) CONTAINS '<lowercase text>'; return names, not nodes;
LIMIT 50; never modify the graph.
Question: {question}""", schema=CYPHER_SCHEMA, use_cache=use_cache)
    usage.add(res)
    cypher = (res["data"] or {}).get("cypher", "").strip().rstrip(";")
    rows, error = [], None
    if not cypher or WRITE_CLAUSES.search(cypher):
        error = "requête refusée (vide ou non read-only)"
    else:
        try:
            rows = run_cypher(cypher)
        except Exception as e:
            error = str(e)[:300]
    return {"approach": "Text2Cypher", "cypher": cypher, "rows": rows, "error": error,
            "answer": rows_to_text(rows) if not error else f"Erreur: {error}",
            "latency_s": round(time.time() - t0, 3), **usage.as_dict()}


def rows_to_text(rows):
    vals = []
    for r in rows:
        for v in r.values():
            if isinstance(v, list):
                vals.extend(str(x) for x in v)
            elif v is not None:
                vals.append(str(v))
    return "; ".join(dict.fromkeys(vals)) if vals else "(aucun résultat)"
