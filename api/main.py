"""Phase 7 - REST API (FastAPI). Swagger UI: http://localhost:8000/docs

Authentication: header `X-API-Key` (see app/auth.py). Custom Cypher requires the analyst role.
"""
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from analytics.queries import CYPHER_QUERIES, GDS_RESULTS
from ui.auth import API_KEYS, allowed
from common.stores import run_cypher
from graphrag.engine import WRITE_CLAUSES, graphrag_answer, text2cypher_answer

app = FastAPI(title="Knowledge Graph Analytics API", version="1.0",
              description="GraphRAG, Text2Cypher and graph analytics over the Neo4j knowledge graph.")


def role_from_key(x_api_key: str = Header(...)):
    role = API_KEYS.get(x_api_key)
    if not role:
        raise HTTPException(401, "Invalid API key")
    return role


class Question(BaseModel):
    question: str


class CypherQuery(BaseModel):
    query: str


@app.get("/health")
def health():
    n = run_cypher("MATCH (e:Entity) RETURN count(e) AS entities")[0]["entities"]
    return {"status": "ok", "entities": n}


@app.post("/ask")
def ask(q: Question, role: str = Depends(role_from_key)):
    res = graphrag_answer(q.question)
    return {k: res[k] for k in ("answer", "cited_documents", "confidence", "latency_s", "input_tokens",
                                "output_tokens", "cost_usd")} | {"triples_used": len(res["triples"])}


@app.post("/text2cypher")
def t2c(q: Question, role: str = Depends(role_from_key)):
    res = text2cypher_answer(q.question)
    return {k: res[k] for k in ("cypher", "rows", "error", "latency_s")}


@app.get("/analytics")
def analytics_list(role: str = Depends(role_from_key)):
    return list({**CYPHER_QUERIES, **GDS_RESULTS})


@app.get("/analytics/{name}")
def analytics_run(name: str, role: str = Depends(role_from_key)):
    catalogue = {**CYPHER_QUERIES, **GDS_RESULTS}
    if name not in catalogue:
        raise HTTPException(404, "Unknown analysis")
    return run_cypher(catalogue[name])


@app.post("/cypher")
def cypher(q: CypherQuery, role: str = Depends(role_from_key)):
    if not allowed(role, "analyst"):
        raise HTTPException(403, "Analyst role required")
    if WRITE_CLAUSES.search(q.query):
        raise HTTPException(400, "Read-only queries only")
    return run_cypher(q.query)
