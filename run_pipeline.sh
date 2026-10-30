#!/usr/bin/env bash
# Runs the full pipeline inside the app container:
#   docker compose exec app bash run_pipeline.sh
set -euo pipefail
cd /workspace

echo "== Phase 1: crawl -> HDFS";                python pipeline/01_crawl.py
echo "== Phase 2: LLM extraction";               python pipeline/02_extract.py
echo "== Phase 3: Spark + entity resolution";    python pipeline/03_spark_transform.py
echo "== Phase 3: load Neo4j + embeddings";      python pipeline/04_load_neo4j.py
echo "== Phase 4: graph analytics (GDS)";        python pipeline/05_graph_analytics.py
echo "== Phase 6: extraction evaluation";        python benchmark/eval_extraction.py
echo "== Phase 6: benchmark";                    python benchmark/run_benchmark.py
echo "Done. UI: http://localhost:8501  API: http://localhost:8000/docs  Neo4j: http://localhost:7475"
