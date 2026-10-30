"""Phase 4 - Run Neo4j Graph Data Science algorithms and the Cypher analytics catalogue."""
import json
import time

from analytics.queries import CYPHER_QUERIES, GDS_RESULTS
from common import config
from common.stores import log_run, run_cypher

GRAPH = "kg"


def run_gds():
    rel_types = [r["relationshipType"] for r in run_cypher("CALL db.relationshipTypes()")
                 if r["relationshipType"] != "MENTIONED_IN"]
    run_cypher("CALL gds.graph.drop($g, false) YIELD graphName RETURN graphName", g=GRAPH)
    proj = run_cypher("""CALL gds.graph.project($g, 'Entity', $rels)
                         YIELD nodeCount, relationshipCount RETURN nodeCount, relationshipCount""",
                      g=GRAPH, rels={t: {"orientation": "UNDIRECTED"} for t in rel_types})[0]
    timings = {}
    for name, q in {
        "pagerank": "CALL gds.pageRank.write($g, {writeProperty: 'pagerank'}) YIELD nodePropertiesWritten RETURN *",
        "louvain": "CALL gds.louvain.write($g, {writeProperty: 'community'}) YIELD communityCount, modularity RETURN *",
        "betweenness": "CALL gds.betweenness.write($g, {writeProperty: 'betweenness'}) YIELD nodePropertiesWritten RETURN *",
        "degree": "CALL gds.degree.write($g, {writeProperty: 'degree'}) YIELD nodePropertiesWritten RETURN *",
        "wcc": "CALL gds.wcc.write($g, {writeProperty: 'component'}) YIELD componentCount RETURN *",
    }.items():
        t0 = time.time()
        timings[name] = {"result": run_cypher(q, g=GRAPH)[0], "seconds": round(time.time() - t0, 3)}
    run_cypher("CALL gds.graph.drop($g) YIELD graphName RETURN graphName", g=GRAPH)
    return proj, timings


def main():
    proj, timings = run_gds()
    results = {"projection": proj, "algorithms": timings, "queries": {}}
    for name, q in {**CYPHER_QUERIES, **GDS_RESULTS}.items():
        t0 = time.time()
        rows = run_cypher(q)
        results["queries"][name] = {"cypher": q.strip(), "rows": rows, "ms": round(1000 * (time.time() - t0), 1)}
        print(f"\n== {name} ({len(rows)} rows)")
        for r in rows[:5]:
            print("  ", r)
    (config.REPORTS / "analytics.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str),
                                                   encoding="utf-8")
    log_run("05_graph_analytics", projected_nodes=proj["nodeCount"], projected_rels=proj["relationshipCount"],
            communities=timings["louvain"]["result"]["communityCount"],
            modularity=round(timings["louvain"]["result"]["modularity"], 3),
            components=timings["wcc"]["result"]["componentCount"])


if __name__ == "__main__":
    main()
