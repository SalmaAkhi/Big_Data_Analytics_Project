"""Phase 7 - Streamlit interface of the knowledge-graph analytics platform."""
import json
import re

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from analytics.queries import CYPHER_QUERIES, GDS_RESULTS
from ui.auth import allowed, check_login
from common import config
from common.stores import run_cypher
from graphrag.engine import WRITE_CLAUSES, graphrag_answer, text2cypher_answer

st.set_page_config(page_title="KG Analytics", page_icon="🕸️", layout="wide")

TYPE_COLORS = {"Company": "#2a6fdb", "Person": "#e8a33d", "Product": "#2ca58d", "Technology": "#8e5cd9",
               "Location": "#d64550", "Organization": "#6b7a8f"}


# ------------------------------------------------------------------ login
if "role" not in st.session_state:
    st.title("🕸️ Plateforme d'analyse de graphe de connaissances")
    st.caption("Big Data · Extraction LLM · Neo4j · GraphRAG")
    with st.form("login"):
        u = st.text_input("Utilisateur")
        p = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Se connecter"):
            role = check_login(u, p)
            if role:
                st.session_state.role, st.session_state.user = role, u
                st.rerun()
            st.error("Identifiants invalides")
    st.info("Comptes de démonstration : viewer / analyst / admin (voir README).")
    st.stop()

role = st.session_state.role
st.sidebar.markdown(f"**Connecté :** `{st.session_state.user}` — rôle **{role}**")
if st.sidebar.button("Se déconnecter"):
    st.session_state.clear()
    st.rerun()
st.sidebar.warning("Les relations sont extraites automatiquement par un LLM : ce sont des **associations "
                   "déduites, pas des faits vérifiés**. Consultez toujours la provenance (documents sources).")

pages = ["Vue d'ensemble", "Explorateur de graphe", "Graph Analytics", "Assistant GraphRAG", "Benchmark"]
if allowed(role, "admin"):
    pages.append("Monitoring pipeline")
page = st.sidebar.radio("Navigation", pages)


def draw_graph(nodes, edges, height=560):
    net = Network(height=f"{height}px", width="100%", directed=True, bgcolor="#ffffff", cdn_resources="in_line")
    net.set_options("""{
      "nodes": {"font": {"size": 18, "strokeWidth": 3, "strokeColor": "#ffffff"},
                "scaling": {"label": {"enabled": true, "min": 16, "max": 26, "drawThreshold": 1}}},
      "edges": {"color": {"opacity": 0.6}, "smooth": false},
      "physics": {"barnesHut": {"gravitationalConstant": -5000, "springLength": 160}, "minVelocity": 0.75,
                  "stabilization": {"iterations": 300}}
    }""")
    for n in nodes.values():
        net.add_node(n["name"], label=n["name"], color=TYPE_COLORS.get(n.get("type"), "#999"),
                     title=f'{n.get("type")}: {n.get("description") or ""}', size=12 + 25 * min(1, (n.get("pagerank") or 0) / 4))
    for e in edges:
        net.add_edge(e["source"], e["target"], label=e["relation"], font={"size": 9}, arrows="to",
                     title=f'docs: {", ".join(e.get("sources") or [])}')
    components.html(net.generate_html(), height=height + 20, scrolling=False)


def legend():
    st.markdown(" ".join(f'<span style="background:{c};color:white;padding:2px 8px;border-radius:8px;'
                         f'font-size:12px">{t}</span>' for t, c in TYPE_COLORS.items()), unsafe_allow_html=True)


def load_json(name):
    p = config.REPORTS / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ------------------------------------------------------------------ pages
if page == "Vue d'ensemble":
    st.title("Vue d'ensemble du graphe de connaissances")
    c = run_cypher("""MATCH (e:Entity) WITH count(e) AS ent
                      MATCH (d:Document) WITH ent, count(d) AS docs
                      MATCH (:Entity)-[r]->(:Entity) RETURN ent, docs, count(r) AS rels""")[0]
    er = load_json("er_stats.json") or {}
    k = st.columns(4)
    k[0].metric("Documents sources", c["docs"])
    k[1].metric("Entités (après résolution)", c["ent"])
    k[2].metric("Relations", c["rels"])
    k[3].metric("Doublons fusionnés", f'{er.get("reduction_pct", "–")} %')
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Entités par type")
        df = pd.DataFrame(run_cypher("MATCH (e:Entity) RETURN e.type AS type, count(*) AS n ORDER BY n DESC"))
        st.bar_chart(df.set_index("type"))
    with col2:
        st.subheader("Relations par type")
        df = pd.DataFrame(run_cypher("""MATCH (:Entity)-[r]->(:Entity) RETURN type(r) AS relation, count(*) AS n
                                        ORDER BY n DESC"""))
        st.bar_chart(df.set_index("relation"))
    st.subheader("Documents par source")
    st.dataframe(pd.DataFrame(run_cypher("""MATCH (d:Document) RETURN split(d.source, ':')[0] AS source,
                                            count(*) AS documents ORDER BY documents DESC""")), hide_index=True)
    if er:
        st.subheader("Résolution d'entités")
        st.dataframe(pd.DataFrame([{"étape": k, "valeur": v} for k, v in er.items() if not isinstance(v, dict)]),
                     hide_index=True)
        merges = load_json("er_merges.json") or []
        with st.expander("Exemples de fusions (alias → entité canonique)"):
            st.dataframe(pd.DataFrame(merges[:40]), hide_index=True)

elif page == "Explorateur de graphe":
    st.title("Explorateur de graphe")
    names = [r["name"] for r in run_cypher("MATCH (e:Entity) RETURN e.name AS name ORDER BY e.pagerank DESC LIMIT 400")]
    default = names.index("OpenAI") if "OpenAI" in names else 0
    c1, c2 = st.columns([3, 1])
    name = c1.selectbox("Entité centrale", names, index=default)
    hops = c2.slider("Profondeur", 1, 2, 1)
    rows = run_cypher(f"""MATCH (s:Entity {{name: $n}})
        MATCH p = (s)-[*1..{hops}]-(o:Entity)
        WHERE all(r IN relationships(p) WHERE type(r) <> 'MENTIONED_IN')
        UNWIND relationships(p) AS r WITH DISTINCT r, startNode(r) AS a, endNode(r) AS b LIMIT 150
        RETURN a{{.name, .type, .description, .pagerank}} AS a, b{{.name, .type, .description, .pagerank}} AS b,
               type(r) AS relation, r.sources AS sources""", n=name)
    nodes, edges = {}, []
    for r in rows:
        nodes[r["a"]["name"]], nodes[r["b"]["name"]] = r["a"], r["b"]
        edges.append({"source": r["a"]["name"], "target": r["b"]["name"], "relation": r["relation"],
                      "sources": r["sources"]})
    legend()
    if nodes:
        draw_graph(nodes, edges)
    info = run_cypher("""MATCH (e:Entity {name: $n}) OPTIONAL MATCH (e)-[:MENTIONED_IN]->(d:Document)
                         RETURN e.type AS type, e.description AS description, e.aliases AS aliases,
                         e.pagerank AS pagerank, e.community AS community,
                         collect(d.title + ' (' + d.source + ')') AS documents""", n=name)[0]
    st.json(info)

elif page == "Graph Analytics":
    st.title("Graph Analytics — Cypher & Graph Data Science")
    catalogue = {**CYPHER_QUERIES, **GDS_RESULTS}
    qname = st.selectbox("Analyse prédéfinie", list(catalogue))
    st.code(catalogue[qname].strip(), language="cypher")
    st.dataframe(pd.DataFrame(run_cypher(catalogue[qname])), hide_index=True, use_container_width=True)
    st.divider()
    st.subheader("Console Cypher (lecture seule)")
    if allowed(role, "analyst"):
        q = st.text_area("Requête", "MATCH (p:Person)-[:FOUNDED]->(c:Company) RETURN p.name, c.name LIMIT 20")
        if st.button("Exécuter"):
            if WRITE_CLAUSES.search(q):
                st.error("Seules les requêtes en lecture sont autorisées.")
            else:
                try:
                    st.dataframe(pd.DataFrame(run_cypher(q)), hide_index=True)
                except Exception as e:
                    st.error(str(e))
    else:
        st.info("🔒 La console Cypher est réservée aux rôles **analyst** et **admin**.")

elif page == "Assistant GraphRAG":
    st.title("Assistant GraphRAG")
    st.caption("Question en langage naturel → liaison d'entités (full-text + vecteurs) → sous-graphe → réponse LLM sourcée")
    examples = ["Who founded the company that acquired DeepMind?",
                "Who is the CEO of the company that develops ChatGPT?",
                "Who founded the company that acquired Instagram?",
                "Which companies invested in the company that develops Claude?",
                "Which companies design semiconductor chips or GPUs?"]
    q = st.selectbox("Exemples", examples)
    q = st.text_input("Votre question", q)
    compare = st.checkbox("Comparer avec Text2Cypher (LLM → Cypher)", value=True)
    if st.button("Demander", type="primary"):
        with st.spinner("Recherche dans le graphe..."):
            res = graphrag_answer(q)
        st.subheader("Réponse GraphRAG")
        st.success(res["answer"])
        k = st.columns(4)
        k[0].metric("Latence", f'{res["latency_s"]:.2f} s')
        k[1].metric("Tokens entrée", res["input_tokens"])
        k[2].metric("Tokens sortie", res["output_tokens"])
        k[3].metric("Confiance", res.get("confidence") or "–")
        docs = run_cypher("MATCH (d:Document) WHERE d.id IN $ids RETURN d.id AS id, d.title AS titre, d.source AS source, d.url AS url",
                          ids=res["cited_documents"])
        st.markdown("**Provenance (documents cités)**")
        st.dataframe(pd.DataFrame(docs), hide_index=True)
        with st.expander(f'Entités liées : {", ".join(s["name"] for s in res["seeds"].values())}'):
            st.json(res["seeds"])
        st.markdown(f'**Sous-graphe récupéré ({len(res["triples"])} triplets)**')
        nodes = {}
        for t in res["triples"][:60]:
            nodes.setdefault(t["source"], {"name": t["source"], "type": t["source_type"]})
            nodes.setdefault(t["target"], {"name": t["target"], "type": t["target_type"]})
        if nodes:
            draw_graph(nodes, res["triples"][:60], height=430)
        if compare:
            with st.spinner("Text2Cypher..."):
                t2c = text2cypher_answer(q)
            st.subheader("Text2Cypher")
            st.code(t2c["cypher"], language="cypher")
            st.write(t2c["answer"])
            st.caption(f'Latence {t2c["latency_s"]:.2f} s · tokens {t2c["input_tokens"]}+{t2c["output_tokens"]}')

elif page == "Benchmark":
    st.title("Benchmark : Cypher expert vs Text2Cypher vs GraphRAG")
    p = config.REPORTS / "benchmark.csv"
    if not p.exists():
        st.warning("Lancez d'abord `python benchmark/run_benchmark.py`.")
        st.stop()
    df = pd.read_csv(p)
    summary = df.groupby("approach").agg(rappel=("recall", "mean"), exact=("exact", "mean"),
                                         latence_s=("latency_s", "mean"), tokens_entree=("input_tokens", "sum"),
                                         cout_usd=("cost_usd", "sum")).round(3)
    st.dataframe(summary, use_container_width=True)
    c1, c2 = st.columns(2)
    c1.subheader("Rappel par catégorie")
    c1.bar_chart(df.pivot_table(index="category", columns="approach", values="recall", aggfunc="mean"))
    c2.subheader("Latence moyenne (s)")
    c2.bar_chart(df.groupby("approach")["latency_s"].mean())
    st.subheader("Détail par question")
    st.dataframe(df[["id", "category", "approach", "recall", "latency_s", "question", "answer"]],
                 hide_index=True, use_container_width=True)
    ev = load_json("extraction_eval.json")
    if ev:
        st.subheader("Qualité de l'extraction")
        k = st.columns(3)
        k[0].metric("Rappel vs Wikidata (tous faits)", f'{ev["wikidata_recall"]["total"]["recall_all"]:.0%}')
        k[1].metric("Rappel (faits présents dans le texte)", f'{ev["wikidata_recall"]["total"]["recall_in_text"]:.0%}')
        k[2].metric("Précision (juge LLM, échantillon)", f'{ev["judged_precision"]["precision"]:.0%}')
        st.dataframe(pd.DataFrame(ev["wikidata_recall"]["per_relation"]).T, use_container_width=True)

elif page == "Monitoring pipeline":
    st.title("Monitoring du pipeline")
    p = config.REPORTS / "pipeline_runs.jsonl"
    runs = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
    st.dataframe(pd.DataFrame(runs).astype(str), hide_index=True, use_container_width=True)
    from common.stores import hdfs_client
    st.subheader("Fichiers HDFS")
    try:
        cl = hdfs_client()
        files = [{"chemin": f"{root}/{name}", "taille_octets": status["length"]}
                 for (root, _), _, fs in cl.walk("/kg", status=True) for name, status in fs]
        st.dataframe(pd.DataFrame(files), hide_index=True, use_container_width=True)
    except Exception as e:
        st.error(f"HDFS indisponible : {e}")
    st.subheader("État Neo4j")
    st.json(run_cypher("CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition"))
