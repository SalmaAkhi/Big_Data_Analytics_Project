"""Connections to HDFS (WebHDFS) and Neo4j."""
import json

from hdfs import InsecureClient
from neo4j import GraphDatabase

from common import config


def hdfs_client():
    return InsecureClient(config.HDFS_URL, user="root")


def hdfs_write_jsonl(path, rows):
    data = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    hdfs_client().write(path, data=data, overwrite=True, encoding="utf-8")


def hdfs_read_jsonl(path):
    with hdfs_client().read(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f.read().splitlines() if line.strip()]


_driver = None


def neo4j_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    return _driver


def run_cypher(query, **params):
    with neo4j_driver().session() as s:
        return [r.data() for r in s.run(query, **params)]


def log_run(step, **info):
    """Append a pipeline-run record (simple monitoring log shown in the UI)."""
    import time
    rec = {"step": step, "time": time.strftime("%Y-%m-%d %H:%M:%S"), **info}
    with open(config.REPORTS / "pipeline_runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[{step}] {info}")
