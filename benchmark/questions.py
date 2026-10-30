"""Phase 6 - Ground-truth question set.

Each question has:
  * category  : single_hop | multi_hop | aggregation | semantic
  * expected  : list of expected answer items, each item = list of accepted aliases (lowercase)
  * cypher    : the query an expert would write by hand ("direct Cypher" approach)
Expected answers come from public facts (Wikipedia / Wikidata), not from the extracted graph,
so they measure both the quality of the graph and of the retrieval method.
"""

QUESTIONS = [
    # ---------------- single hop
    {"id": "Q01", "category": "single_hop", "question": "Who founded Nvidia?",
     "expected": [["jensen huang"], ["malachowsky"], ["priem"]],
     "cypher": "MATCH (p:Person)-[:FOUNDED]->(c) WHERE toLower(c.name) CONTAINS 'nvidia' RETURN DISTINCT p.name AS name"},
    {"id": "Q02", "category": "single_hop", "question": "Which company acquired GitHub?",
     "expected": [["microsoft"]],
     "cypher": "MATCH (a)-[:ACQUIRED|OWNS]->(c) WHERE toLower(c.name) CONTAINS 'github' RETURN DISTINCT a.name AS name"},
    {"id": "Q03", "category": "single_hop", "question": "Which company acquired Red Hat?",
     "expected": [["ibm"]],
     "cypher": "MATCH (a)-[:ACQUIRED|OWNS]->(c) WHERE toLower(c.name) CONTAINS 'red hat' RETURN DISTINCT a.name AS name"},
    {"id": "Q04", "category": "single_hop", "question": "Which company acquired VMware?",
     "expected": [["broadcom"]],
     "cypher": "MATCH (a)-[:ACQUIRED|OWNS]->(c) WHERE toLower(c.name) CONTAINS 'vmware' RETURN DISTINCT a.name AS name"},
    {"id": "Q05", "category": "single_hop", "question": "Which company acquired Mobileye?",
     "expected": [["intel"]],
     "cypher": "MATCH (a)-[:ACQUIRED|OWNS]->(c) WHERE toLower(c.name) CONTAINS 'mobileye' RETURN DISTINCT a.name AS name"},
    {"id": "Q06", "category": "single_hop", "question": "Who is the CEO of Nvidia?",
     "expected": [["jensen huang"]],
     "cypher": "MATCH (p:Person)-[:CEO_OF]->(c) WHERE toLower(c.name) CONTAINS 'nvidia' RETURN DISTINCT p.name AS name"},
    {"id": "Q07", "category": "single_hop", "question": "Where is Apple headquartered?",
     "expected": [["cupertino"]],
     "cypher": "MATCH (c)-[:HEADQUARTERED_IN]->(l) WHERE toLower(c.name) STARTS WITH 'apple' RETURN DISTINCT l.name AS name"},
    # ---------------- aggregation (completeness matters)
    {"id": "Q08", "category": "aggregation", "question": "Which companies has Microsoft acquired?",
     "expected": [["linkedin"], ["github"], ["activision"]],
     "cypher": "MATCH (m)-[:ACQUIRED]->(c) WHERE toLower(m.name) = 'microsoft' RETURN DISTINCT c.name AS name"},
    {"id": "Q09", "category": "aggregation", "question": "Which companies did Elon Musk found or co-found?",
     "expected": [["spacex"], ["tesla"], ["neuralink"], ["xai"], ["openai"], ["paypal", "x.com"]],
     "cypher": "MATCH (p)-[:FOUNDED]->(c) WHERE toLower(p.name) CONTAINS 'elon musk' RETURN DISTINCT c.name AS name"},
    {"id": "Q10", "category": "aggregation", "question": "Which companies has Google acquired?",
     "expected": [["youtube"], ["deepmind"], ["android"]],
     "cypher": "MATCH (g)-[:ACQUIRED]->(c) WHERE toLower(g.name) IN ['google', 'alphabet', 'alphabet inc.', 'google llc'] RETURN DISTINCT c.name AS name"},
    # ---------------- multi hop
    {"id": "Q11", "category": "multi_hop", "question": "Who founded the company that acquired Instagram?",
     "expected": [["zuckerberg"], ["saverin"], ["moskovitz"], ["chris hughes"], ["mccollum"]],
     "cypher": """MATCH (a)-[:ACQUIRED|OWNS]->(i) WHERE toLower(i.name) CONTAINS 'instagram'
                  MATCH (p:Person)-[:FOUNDED]->(a) RETURN DISTINCT p.name AS name"""},
    {"id": "Q12", "category": "multi_hop", "question": "Where is the company that acquired Red Hat headquartered?",
     "expected": [["armonk"]],
     "cypher": """MATCH (a)-[:ACQUIRED|OWNS]->(c) WHERE toLower(c.name) CONTAINS 'red hat'
                  MATCH (a)-[:HEADQUARTERED_IN]->(l) RETURN DISTINCT l.name AS name"""},
    {"id": "Q13", "category": "multi_hop", "question": "Who is the CEO of the company that develops ChatGPT?",
     "expected": [["sam altman"]],
     "cypher": """MATCH (c)-[:DEVELOPS]->(x) WHERE toLower(x.name) CONTAINS 'chatgpt'
                  MATCH (p:Person)-[:CEO_OF]->(c) RETURN DISTINCT p.name AS name"""},
    {"id": "Q14", "category": "multi_hop", "question": "Who founded the company that acquired DeepMind?",
     "expected": [["larry page"], ["sergey brin"]],
     "cypher": """MATCH (a)-[:ACQUIRED|OWNS]->(d) WHERE toLower(d.name) CONTAINS 'deepmind'
                  MATCH (p:Person)-[:FOUNDED]->(a) RETURN DISTINCT p.name AS name"""},
    {"id": "Q15", "category": "multi_hop",
     "question": "Who founded the company that develops Claude, and which company did they work for before?",
     "expected": [["dario amodei"], ["daniela amodei"], ["openai"]],
     "cypher": """MATCH (p:Person)-[:FOUNDED]->(c)-[:DEVELOPS]->(x) WHERE toLower(x.name) CONTAINS 'claude'
                  OPTIONAL MATCH (p)-[:WORKS_FOR]->(w) WHERE w <> c
                  RETURN DISTINCT p.name AS name, collect(DISTINCT w.name) AS previous"""},
    {"id": "Q16", "category": "multi_hop", "question": "Which companies invested in the company that develops Claude?",
     "expected": [["amazon"], ["google"]],
     "cypher": """MATCH (c)-[:DEVELOPS]->(x) WHERE toLower(x.name) CONTAINS 'claude'
                  MATCH (i)-[:INVESTED_IN]->(c) RETURN DISTINCT i.name AS name"""},
    {"id": "Q17", "category": "multi_hop", "question": "Who is the CEO of the company that owns WhatsApp?",
     "expected": [["zuckerberg"]],
     "cypher": """MATCH (a)-[:ACQUIRED|OWNS]->(w) WHERE toLower(w.name) CONTAINS 'whatsapp'
                  MATCH (p:Person)-[:CEO_OF]->(a) RETURN DISTINCT p.name AS name"""},
    {"id": "Q18", "category": "multi_hop", "question": "Who founded the company that acquired Slack?",
     "expected": [["benioff"], ["parker harris"]],
     "cypher": """MATCH (a)-[:ACQUIRED|OWNS]->(s) WHERE toLower(s.name) STARTS WITH 'slack'
                  MATCH (p:Person)-[:FOUNDED]->(a) RETURN DISTINCT p.name AS name"""},
    # ---------------- semantic (vocabulary not in the schema)
    {"id": "Q19", "category": "semantic", "question": "Which companies design semiconductor chips or GPUs?",
     "expected": [["nvidia"], ["amd", "advanced micro devices"], ["intel"], ["arm"], ["broadcom"]],
     "cypher": """MATCH (c:Company) WHERE any(k IN ['chip', 'semiconductor', 'gpu', 'processor']
                  WHERE toLower(c.description) CONTAINS k) RETURN DISTINCT c.name AS name"""},
    {"id": "Q20", "category": "semantic", "question": "Which companies build large language models or AI chatbots?",
     "expected": [["openai"], ["anthropic"], ["mistral"], ["xai"], ["deepmind", "google"]],
     "cypher": """MATCH (c:Company) WHERE any(k IN ['artificial intelligence', 'language model', 'chatbot', ' ai ']
                  WHERE toLower(' ' + c.description + ' ') CONTAINS k) RETURN DISTINCT c.name AS name"""},
    {"id": "Q21", "category": "semantic", "question": "Which companies are involved in electric vehicles or spaceflight?",
     "expected": [["tesla"], ["spacex"]],
     "cypher": """MATCH (c:Company) WHERE any(k IN ['electric vehicle', 'spacecraft', 'rocket', 'spaceflight', 'space']
                  WHERE toLower(c.description) CONTAINS k) RETURN DISTINCT c.name AS name"""},
]
