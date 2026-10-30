"""Phase 1 - Ingestion: crawl heterogeneous sources and store raw data in HDFS.

Sources:
  * Wikipedia articles (unstructured text, MediaWiki JSON API)
  * Tech news RSS feeds (semi-structured XML)
  * Local documents in data/local_docs (*.txt, *.md)
  * Wikidata facts (structured, SPARQL) -> kept apart as ground truth for evaluation
"""
import html
import re
import time
from pathlib import Path

import feedparser
import requests

from common import config
from common.stores import hdfs_client, hdfs_write_jsonl, log_run

UA = {"User-Agent": "KGStudentProject/1.0 (https://www.mediawiki.org/wiki/API:Etiquette; educational use) python-requests/2.32"}


def get(url, **kw):
    """GET with polite retries (Wikimedia answers 429 when requests are too fast)."""
    for attempt in range(6):
        r = requests.get(url, headers=UA, timeout=60, **kw)
        if r.status_code == 200:
            return r
        time.sleep(int(r.headers.get("retry-after", 0) or 0) or 5 * (attempt + 1))
    r.raise_for_status()
    return r
MAX_CHARS = 9000  # keep intro + history sections, limits LLM cost


def crawl_wikipedia():
    docs = []
    for title in config.COMPANIES:
        params = {"action": "query", "prop": "extracts|pageprops|info", "inprop": "url", "explaintext": 1,
                  "redirects": 1, "titles": title, "format": "json", "formatversion": 2}
        r = get("https://en.wikipedia.org/w/api.php", params=params)
        page = r.json()["query"]["pages"][0]
        text = page.get("extract", "")
        # drop low-value trailing sections
        text = re.split(r"\n==+ (See also|References|External links|Notes|Further reading) ==+", text)[0]
        docs.append({
            "doc_id": f"wiki_{len(docs):03d}",
            "source": "wikipedia",
            "title": page["title"],
            "url": page.get("fullurl", ""),
            "wikidata_id": page.get("pageprops", {}).get("wikibase_item"),
            "text": text[:MAX_CHARS],
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        time.sleep(1.0)
    return docs


def _clean_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def crawl_rss(max_items=20):
    keywords = [re.sub(r"\s*\(.*\)|,? Inc\.?| Platforms| Corporation| Holdings| Electronics| Technologies", "", c)
                for c in config.COMPANIES]
    docs = []
    for feed_name, url in config.RSS_FEEDS.items():
        try:
            resp = requests.get(url, headers=UA, timeout=30)
            feed = feedparser.parse(resp.content)
        except Exception as e:  # a failing feed must not stop the pipeline
            print(f"RSS {feed_name} failed: {e}")
            continue
        for entry in feed.entries:
            body = _clean_html(entry.get("summary", ""))
            if entry.get("content"):
                body = _clean_html(entry.content[0].get("value", ""))
            text = f"{entry.get('title', '')}. {body}"
            if not any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords):
                continue
            docs.append({
                "doc_id": f"rss_{len(docs):03d}",
                "source": f"rss:{feed_name}",
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "text": text[:4000],
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            if len(docs) >= max_items:
                return docs
    return docs


def load_local_docs():
    docs = []
    for p in sorted((config.DATA / "local_docs").glob("*.*")):
        if p.suffix.lower() in {".txt", ".md"}:
            docs.append({"doc_id": f"local_{len(docs):03d}", "source": "local", "title": p.stem,
                         "url": f"file://{p.name}", "text": p.read_text(encoding="utf-8")[:MAX_CHARS],
                         "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return docs


WIKIDATA_PROPS = {"P112": "FOUNDED", "P169": "CEO_OF", "P159": "HEADQUARTERED_IN",
                  "P749": "SUBSIDIARY_OF", "P127": "OWNED_BY"}


def crawl_wikidata(qids):
    values = " ".join(f"wd:{q}" for q in qids if q)
    props = " ".join(f"wdt:{p}" for p in WIKIDATA_PROPS)
    query = f"""
    SELECT ?item ?itemLabel ?prop ?value ?valueLabel WHERE {{
      VALUES ?item {{ {values} }}
      VALUES ?prop {{ {props} }}
      ?item ?prop ?value .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    r = get("https://query.wikidata.org/sparql", params={"query": query, "format": "json"})
    facts = []
    for b in r.json()["results"]["bindings"]:
        pid = b["prop"]["value"].rsplit("/", 1)[-1]
        facts.append({"qid": b["item"]["value"].rsplit("/", 1)[-1], "subject": b["itemLabel"]["value"], "property": pid, "relation": WIKIDATA_PROPS[pid],
                      "object": b["valueLabel"]["value"]})
    return facts


def main():
    t0 = time.time()
    wiki = crawl_wikipedia()
    rss = crawl_rss()
    local = load_local_docs()
    facts = crawl_wikidata([d["wikidata_id"] for d in wiki])

    client = hdfs_client()
    client.makedirs(config.HDFS_RAW)
    hdfs_write_jsonl(f"{config.HDFS_RAW}/wikipedia/docs.jsonl", wiki)
    hdfs_write_jsonl(f"{config.HDFS_RAW}/rss/docs.jsonl", rss)
    if local:
        hdfs_write_jsonl(f"{config.HDFS_RAW}/local/docs.jsonl", local)
    hdfs_write_jsonl(f"{config.HDFS_RAW}/wikidata/facts.jsonl", facts)

    log_run("01_crawl", wikipedia_docs=len(wiki), rss_docs=len(rss), local_docs=len(local),
            wikidata_facts=len(facts), chars=sum(len(d["text"]) for d in wiki + rss + local),
            seconds=round(time.time() - t0, 1))
    for path in client.list(config.HDFS_RAW):
        print("HDFS", f"{config.HDFS_RAW}/{path}", client.list(f"{config.HDFS_RAW}/{path}"))


if __name__ == "__main__":
    main()
