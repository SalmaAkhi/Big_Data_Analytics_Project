"""Phase 4 - Graph analytics catalogue: Cypher queries and Neo4j GDS algorithms."""

CYPHER_QUERIES = {
    "Statistiques par type d'entité": """
        MATCH (e:Entity) RETURN e.type AS type, count(*) AS entites ORDER BY entites DESC""",
    "Statistiques par type de relation": """
        MATCH ()-[r]->() WHERE type(r) <> 'MENTIONED_IN'
        RETURN type(r) AS relation, count(*) AS nombre ORDER BY nombre DESC""",
    "Entités les plus connectées (degré)": """
        MATCH (e:Entity)-[r]-(:Entity)
        RETURN e.name AS entite, e.type AS type, count(r) AS degre ORDER BY degre DESC LIMIT 15""",
    "Acquisitions (qui a racheté qui)": """
        MATCH (a:Entity)-[r:ACQUIRED]->(b:Entity)
        RETURN a.name AS acquereur, b.name AS cible, r.weight AS mentions ORDER BY a.name LIMIT 50""",
    "Fondateurs en série (≥ 2 entreprises)": """
        MATCH (p:Person)-[:FOUNDED]->(c)
        WITH p, collect(DISTINCT c.name) AS entreprises WHERE size(entreprises) >= 2
        RETURN p.name AS fondateur, entreprises, size(entreprises) AS n ORDER BY n DESC""",
    "Multi-hop : fondateurs des entreprises acquises par Google/Alphabet": """
        MATCH (g:Company)-[:ACQUIRED|OWNS]->(c)<-[:FOUNDED]-(p:Person)
        WHERE toLower(g.name) CONTAINS 'google' OR toLower(g.name) CONTAINS 'alphabet'
        RETURN g.name AS acquereur, c.name AS entreprise, collect(p.name) AS fondateurs""",
    "Plus court chemin Elon Musk → Microsoft": """
        MATCH (a:Entity), (b:Entity)
        WHERE toLower(a.name) CONTAINS 'elon musk' AND toLower(b.name) = 'microsoft'
        MATCH p = shortestPath((a)-[*..6]-(b))
        WHERE none(r IN relationships(p) WHERE type(r) = 'MENTIONED_IN')
        RETURN [n IN nodes(p) | n.name] AS chemin, [r IN relationships(p) | type(r)] AS relations LIMIT 1""",
    "Villes avec le plus de sièges sociaux": """
        MATCH (c)-[:HEADQUARTERED_IN]->(l:Location)
        RETURN l.name AS lieu, collect(c.name) AS entreprises, count(c) AS n ORDER BY n DESC LIMIT 10""",
    "Provenance : relations confirmées par plusieurs documents": """
        MATCH (a)-[r]->(b) WHERE type(r) <> 'MENTIONED_IN' AND size(r.sources) >= 2
        RETURN a.name AS source, type(r) AS relation, b.name AS cible, size(r.sources) AS nb_documents
        ORDER BY nb_documents DESC LIMIT 20""",
}

GDS_RESULTS = {
    "Top PageRank (influence)": """
        MATCH (e:Entity) WHERE e.pagerank IS NOT NULL
        RETURN e.name AS entite, e.type AS type, round(e.pagerank, 3) AS pagerank ORDER BY pagerank DESC LIMIT 15""",
    "Top Betweenness (entités « pont »)": """
        MATCH (e:Entity) WHERE e.betweenness IS NOT NULL
        RETURN e.name AS entite, e.type AS type, round(e.betweenness, 1) AS betweenness ORDER BY betweenness DESC LIMIT 15""",
    "Communautés Louvain (les plus grandes)": """
        MATCH (e:Entity) WHERE e.community IS NOT NULL
        WITH e.community AS communaute, e ORDER BY e.pagerank DESC
        WITH communaute, collect(e.name) AS membres, count(*) AS taille
        RETURN communaute, taille, membres[0..10] AS principaux_membres ORDER BY taille DESC LIMIT 10""",
}
