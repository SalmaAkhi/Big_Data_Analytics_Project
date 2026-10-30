"""Phase 2b + 3 - Spark transformations and entity resolution.

Reads raw LLM extractions from HDFS, flattens entities / relations, resolves duplicate entities,
validates relations against the schema, aggregates provenance and writes curated Parquet to HDFS.
"""
import json
import time

from pyspark.sql import SparkSession, functions as F, types as T

from common import config
from common.entity_resolution import norm_key, resolve
from common.stores import log_run


def main():
    t0 = time.time()
    spark = (SparkSession.builder.appName("kg-transform").master(config.SPARK_MASTER)
             .config("spark.hadoop.fs.defaultFS", config.HDFS_FS)
             .config("spark.sql.shuffle.partitions", "8")
             .config("spark.ui.port", "4040")
             .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")

    raw = spark.read.json(f"{config.HDFS_FS}{config.HDFS_EXTRACTED}/extractions.jsonl")
    docs = spark.read.json(f"{config.HDFS_FS}{config.HDFS_EXTRACTED}/documents.jsonl")

    ents = (raw.select("doc_id", F.explode("entities").alias("e"))
            .select("doc_id", F.trim(F.col("e.name")).alias("name"), F.col("e.type").alias("type"),
                    F.col("e.description").alias("description"))
            .filter(F.length("name") > 1))
    rels = (raw.select("doc_id", "title", F.explode("relations").alias("r"))
            .select("doc_id", "title", F.trim(F.col("r.source")).alias("src"), F.upper(F.col("r.relation")).alias("rel"),
                    F.trim(F.col("r.target")).alias("tgt"), F.col("r.evidence").alias("evidence")))

    # ---- entity resolution: distinct surface forms are small enough to resolve on the driver ----
    mentions = [(r["name"], r["type"], r["cnt"]) for r in
                ents.groupBy("name", "type").agg(F.count("*").alias("cnt")).collect()]
    mapping, stats, merges = resolve(mentions)
    bmap = spark.sparkContext.broadcast(mapping)

    res_type = T.StructType([T.StructField("id", T.StringType()), T.StructField("cname", T.StringType()),
                             T.StructField("ctype", T.StringType())])

    @F.udf(res_type)
    def lookup(name):
        hit = bmap.value.get(norm_key(name))
        return hit if hit else None

    ents_r = ents.withColumn("res", lookup("name")).filter(F.col("res").isNotNull())
    entities = (ents_r.groupBy(F.col("res.id").alias("id"))
                .agg(F.first("res.cname").alias("name"), F.first("res.ctype").alias("type"),
                     F.max_by("description", F.length("description")).alias("description"),
                     F.array_sort(F.collect_set("name")).alias("aliases"),
                     F.count("*").alias("mentions"),
                     F.array_sort(F.collect_set("doc_id")).alias("doc_ids")))

    # ---- relations: resolve endpoints, validate, aggregate provenance ----
    valid_rel = F.col("rel").isin(list(config.RELATION_TYPES))
    rels_r = (rels.withColumn("s", lookup("src")).withColumn("t", lookup("tgt"))
              .filter(F.col("s").isNotNull() & F.col("t").isNotNull() & valid_rel)
              .filter(F.col("s.id") != F.col("t.id")))
    dropped = rels.count() - rels_r.count()
    relations = (rels_r.groupBy(F.col("s.id").alias("src_id"), "rel", F.col("t.id").alias("tgt_id"))
                 .agg(F.count("*").alias("weight"),
                      F.array_sort(F.collect_set("doc_id")).alias("doc_ids"),
                      F.slice(F.collect_set("evidence"), 1, 3).alias("evidence")))

    out = f"{config.HDFS_FS}{config.HDFS_CURATED}"
    entities.write.mode("overwrite").parquet(f"{out}/entities")
    relations.write.mode("overwrite").parquet(f"{out}/relations")
    docs.write.mode("overwrite").parquet(f"{out}/documents")

    n_ent, n_rel = entities.count(), relations.count()
    by_type = {r["type"]: r["count"] for r in entities.groupBy("type").count().collect()}
    by_rel = {r["rel"]: r["count"] for r in relations.groupBy("rel").count().collect()}
    stats.update({"relations_raw": rels.count(), "relations_dropped_invalid": dropped,
                  "relations_curated": n_rel, "entities_by_type": by_type, "relations_by_type": by_rel})
    (config.REPORTS / "er_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    (config.REPORTS / "er_merges.json").write_text(json.dumps(merges[:200], indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    log_run("03_spark_transform", entities=n_ent, relations=n_rel, er=stats, seconds=round(time.time() - t0, 1))
    spark.stop()


if __name__ == "__main__":
    main()
