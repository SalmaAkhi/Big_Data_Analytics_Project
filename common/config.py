"""Shared configuration: graph schema, paths and connection settings."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPORTS = DATA / "reports"
CACHE = DATA / "cache"
for _d in (DATA, REPORTS, CACHE):
    _d.mkdir(parents=True, exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODELS = [m.strip() for m in os.getenv("GEMINI_MODELS", "gemini-3.5-flash-lite").split(",") if m.strip()]
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "local")  # local | gemini
LOCAL_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384 if EMBED_BACKEND == "local" else 768

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "kgpassword123")

HDFS_URL = os.getenv("HDFS_URL", "http://localhost:9870")
HDFS_FS = "hdfs://namenode:9000"
HDFS_RAW = "/kg/raw"
HDFS_EXTRACTED = "/kg/extracted"
HDFS_CURATED = "/kg/curated"
SPARK_MASTER = os.getenv("SPARK_MASTER", "local[*]")

# Estimated price per 1M tokens (USD), used to compare inference cost between approaches
PRICE_INPUT_PER_M = 0.10
PRICE_OUTPUT_PER_M = 0.40

# ---- Shared graph schema (used by extraction, loading, Text2Cypher and GraphRAG) ----
ENTITY_TYPES = ["Company", "Person", "Product", "Technology", "Location", "Organization"]

# relation -> (allowed source types, allowed target types, meaning)
RELATION_TYPES = {
    "FOUNDED": ("Person|Company", "Company|Organization|Product", "source founded or co-founded target"),
    "CEO_OF": ("Person", "Company|Organization", "source is or was CEO of target"),
    "WORKS_FOR": ("Person", "Company|Organization", "source works or worked for target (not CEO)"),
    "ACQUIRED": ("Company", "Company|Product", "source acquired or bought target"),
    "OWNS": ("Company|Person", "Company|Product", "source owns target (without explicit acquisition)"),
    "SUBSIDIARY_OF": ("Company", "Company", "source is a subsidiary / division of target"),
    "INVESTED_IN": ("Company|Person|Organization", "Company", "source invested in target"),
    "DEVELOPS": ("Company|Person|Organization", "Product|Technology", "source develops / makes target"),
    "HEADQUARTERED_IN": ("Company|Organization", "Location", "source has its headquarters in target"),
    "PARTNERS_WITH": ("Company|Organization", "Company|Organization", "partnership or collaboration"),
    "COMPETES_WITH": ("Company", "Company", "source competes with target"),
    "RELATED_TO": ("*", "*", "any other meaningful relation (use rarely)"),
}

# Companies whose Wikipedia articles form the main corpus
COMPANIES = [
    "Apple Inc.", "Microsoft", "Google", "Alphabet Inc.", "Meta Platforms", "Amazon (company)",
    "Nvidia", "OpenAI", "Anthropic", "Tesla, Inc.", "SpaceX", "Instagram", "WhatsApp", "YouTube",
    "LinkedIn", "GitHub", "Google DeepMind", "Activision Blizzard", "Twitter", "Oracle Corporation",
    "IBM", "Intel", "AMD", "Arm Holdings", "Samsung Electronics", "Netflix", "Uber", "Airbnb",
    "Salesforce", "Slack Technologies", "Adobe Inc.", "Figma", "Mobileye", "Red Hat", "VMware",
    "Broadcom", "Mistral AI", "xAI (company)", "Neuralink", "PayPal",
]

RSS_FEEDS = {
    "techcrunch": "https://techcrunch.com/feed/",
    "theverge": "https://www.theverge.com/rss/index.xml",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
}
