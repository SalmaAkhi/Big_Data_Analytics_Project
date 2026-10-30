"""Phase 3 - Load the curated graph from HDFS (Parquet, read with Spark) into Neo4j.

Also computes entity embeddings (Gemini) and creates the vector + full-text indexes used by GraphRAG.
"""
import time

from pyspark.sql import SparkSession

from common import config, llm
from common.stores import log_run, neo4j_driver

BATCH = 500


def batches(rows, n=BATCH):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def main():
    t0 = time.time()
    spark = (SparkSession.builder.appName("kg-load").master(config.SPARK_MASTER)
             .config("spark.hadoop.fs.defaultFS", config.HDFS_FS).getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    base = f"{config.HDFS_FS}{config.HDFS_CURATED}"
    entities = [r.asDict(recursive=True) for r in spark.read.parquet(f"{base}/entities").collect()]
    relations = [r.asDict(recursive=True) for r in spark.read.parquet(f"{base}/relations").collect()]
    documents = [r.asDict(recursive=True) for r in spark.read.parquet(f"{base}/documents").collect()]
    spark.stop()

    print(f"Embedding {len(entities)} entities...")
    vectors = llm.embed([f"{e['name']} ({e['type']}): {e['description'] or ''}" for e in entities])
    for e, v in zip(entities, vectors):
        e["embedding"] = v

    with neo4j_driver().session() as s:
        s.run("MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS")
        for q in [
            "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)",
            "CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.aliases_text]",
            f"""CREATE VECTOR INDEX entity_embedding IF NOT EXISTS FOR (e:Entity) ON (e.embedding)
                OPTIONS {{indexConfig: {{`vector.dimensions`: {config.EMBED_DIM}, `vector.similarity_function`: 'cosine'}}}}""",
        ]:
            s.run(q)

        s.run("UNWIND $rows AS d MERGE (n:Document {id: d.doc_id}) SET n.title = d.title, n.url = d.url, n.source = d.source",
              rows=documents)

        for chunk in batches(entities):
            s.run("""UNWIND $rows AS e
                     MERGE (n:Entity {id: e.id})
                     SET n.name = e.name, n.type = e.type, n.description = e.description,
                         n.aliases = e.aliases, n.aliases_text = apoc.text.join(e.aliases, ' | '),
                         n.mentions = e.mentions, n.doc_ids = e.doc_ids
                     WITH n, e CALL db.create.setNodeVectorProperty(n, 'embedding', e.embedding)
                     WITH n, e UNWIND e.doc_ids AS did
                     MATCH (d:Document {id: did}) MERGE (n)-[:MENTIONED_IN]->(d)""", rows=chunk)
        for t in config.ENTITY_TYPES:  # labels come from a fixed whitelist -> safe interpolation
            s.run(f"MATCH (n:Entity {{type: $t}}) SET n:{t}", t=t)

        for rel in config.RELATION_TYPES:
            rows = [r for r in relations if r["rel"] == rel]
            for chunk in batches(rows):
                s.run(f"""UNWIND $rows AS r
                          MATCH (a:Entity {{id: r.src_id}}), (b:Entity {{id: r.tgt_id}})
                          MERGE (a)-[x:{rel}]->(b)
                          SET x.weight = r.weight, x.sources = r.doc_ids, x.evidence = r.evidence""", rows=chunk)

        counts = s.run("""MATCH (n) WITH count(n) AS nodes
                          MATCH ()-[r]->() RETURN nodes, count(r) AS rels""").single().data()
    log_run("04_load_neo4j", entities=len(entities), relations=len(relations), documents=len(documents),
            neo4j_nodes=counts["nodes"], neo4j_relationships=counts["rels"], seconds=round(time.time() - t0, 1))


if __name__ == "__main__":
    main()
