"""Phase 6 - Comparative benchmark: expert Cypher vs Text2Cypher (LLM) vs GraphRAG.

Metrics per question and approach:
  * recall      : share of expected answer items found in the answer (completeness)
  * exact       : 1 if every expected item is found
  * latency_s   : end-to-end time
  * tokens/cost : LLM inference cost (0 for expert Cypher)
"""
import json
import re
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from benchmark.questions import QUESTIONS
from common import config
from common.stores import log_run, run_cypher
from graphrag.engine import graphrag_answer, rows_to_text, text2cypher_answer

FIG = config.REPORTS / "figures"
FIG.mkdir(parents=True, exist_ok=True)


def score(answer, expected):
    text = (answer or "").lower()
    hits = [any(re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", text) for a in item) for item in expected]
    return sum(hits) / len(expected), hits


def expert_cypher(q):
    t0 = time.time()
    rows = run_cypher(q["cypher"])
    return {"approach": "Cypher expert", "answer": rows_to_text(rows), "latency_s": round(time.time() - t0, 3),
            "input_tokens": 0, "output_tokens": 0, "llm_calls": 0, "cost_usd": 0.0}


def main():
    records, details = [], []
    for q in QUESTIONS:
        for fn in (expert_cypher, text2cypher_answer, graphrag_answer):
            try:
                res = fn(q) if fn is expert_cypher else fn(q["question"], use_cache=False)
            except Exception as e:
                res = {"approach": {expert_cypher: "Cypher expert", text2cypher_answer: "Text2Cypher",
                                    graphrag_answer: "GraphRAG"}[fn], "answer": f"Erreur: {e}", "latency_s": 0,
                       "input_tokens": 0, "output_tokens": 0, "llm_calls": 0, "cost_usd": 0}
            rec, hits = score(res["answer"], q["expected"])
            records.append({"id": q["id"], "category": q["category"], "question": q["question"],
                            "approach": res["approach"], "recall": round(rec, 3), "exact": int(rec == 1.0),
                            "latency_s": res["latency_s"], "input_tokens": res["input_tokens"],
                            "output_tokens": res["output_tokens"], "cost_usd": res["cost_usd"],
                            "answer": res["answer"][:500]})
            details.append({**{k: v for k, v in res.items() if k not in ("seeds",)}, "id": q["id"], "hits": hits,
                            "expected": q["expected"]})
            print(f"{q['id']} {res['approach']:<14} recall={rec:.2f} {res['latency_s']:.2f}s  {res['answer'][:90]!r}")
            time.sleep(0.5)

    df = pd.DataFrame(records)
    df.to_csv(config.REPORTS / "benchmark.csv", index=False, encoding="utf-8")
    (config.REPORTS / "benchmark_details.json").write_text(
        json.dumps(details, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    summary = df.groupby("approach").agg(recall=("recall", "mean"), exact=("exact", "mean"),
                                         latency_s=("latency_s", "mean"), tokens_in=("input_tokens", "sum"),
                                         tokens_out=("output_tokens", "sum"), cost_usd=("cost_usd", "sum")).round(4)
    by_cat = df.pivot_table(index="category", columns="approach", values="recall", aggfunc="mean").round(3)
    summary.to_csv(config.REPORTS / "benchmark_summary.csv")
    by_cat.to_csv(config.REPORTS / "benchmark_by_category.csv")
    print("\n", summary, "\n\n", by_cat)

    order = ["Cypher expert", "Text2Cypher", "GraphRAG"]
    colors = {"Cypher expert": "#2a6fdb", "Text2Cypher": "#e8a33d", "GraphRAG": "#2ca58d"}
    cats = ["single_hop", "multi_hop", "aggregation", "semantic"]
    ax = by_cat.reindex(cats)[order].plot.bar(figsize=(8, 4.2), color=[colors[o] for o in order], rot=0, width=0.75)
    ax.set_ylabel("Rappel moyen (complétude)"); ax.set_ylim(0, 1.05); ax.set_xlabel("")
    ax.set_title("Qualité des réponses par type de question"); ax.grid(axis="y", alpha=.3); ax.legend(frameon=False)
    plt.tight_layout(); plt.savefig(FIG / "benchmark_recall_by_category.png", dpi=160); plt.close()

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    s = summary.reindex(order)
    for ax, (col, title) in zip(axes, [("recall", "Rappel moyen"), ("latency_s", "Latence moyenne (s)"),
                                       ("tokens_in", "Tokens d'entrée (total)")]):
        ax.bar(s.index, s[col], color=[colors[o] for o in order])
        ax.set_title(title); ax.tick_params(axis="x", labelsize=8); ax.grid(axis="y", alpha=.3)
    plt.tight_layout(); plt.savefig(FIG / "benchmark_tradeoffs.png", dpi=160); plt.close()

    log_run("06_benchmark", questions=len(QUESTIONS),
            **{f"recall_{a}": float(summary.loc[a, "recall"]) for a in summary.index})


if __name__ == "__main__":
    main()
