"""Entity resolution: map surface forms of the same real-world entity to one canonical id.

Three steps, each measured separately for the report:
  1. normalisation (case, accents, punctuation, corporate suffixes)
  2. type harmonisation (same key, different types -> majority type)
  3. fuzzy matching within a type (rapidfuzz) + person surname rule
"""
import re
import unicodedata
from collections import Counter, defaultdict

from rapidfuzz import fuzz

SUFFIXES = r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|plc|sa|ag|gmbh|holdings|group|platforms|technologies)\b"
FUZZY_THRESHOLD = 93


def norm_key(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"^the ", "", s.strip())
    stripped = re.sub(SUFFIXES, " ", s)
    s = stripped if stripped.strip() else s  # never strip a name down to nothing
    return re.sub(r"\s+", " ", s).strip()


def resolve(mentions):
    """mentions: list of (surface_name, type, count). Returns (mapping, stats, merges).

    mapping: norm_key(surface_name) -> (canonical_id, canonical_name, canonical_type)
    """
    # 1. normalisation
    by_key = defaultdict(Counter)       # key -> Counter(type)
    surfaces = defaultdict(Counter)     # key -> Counter(surface)
    for name, typ, cnt in mentions:
        k = norm_key(name)
        if not k:
            continue
        by_key[k][typ] += cnt
        surfaces[k][name] += cnt

    # 2. type harmonisation: one type per key
    key_type = {k: c.most_common(1)[0][0] for k, c in by_key.items()}

    # 3. fuzzy merge inside each type (union-find)
    parent = {k: k for k in key_type}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def weight(k):
        return sum(surfaces[k].values())

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            # the more frequent key becomes the root
            if weight(ra) < weight(rb):
                ra, rb = rb, ra
            parent[rb] = ra

    by_type = defaultdict(list)
    for k, t in key_type.items():
        by_type[t].append(k)
    fuzzy_merges = []
    for t, keys in by_type.items():
        keys.sort()
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if abs(len(a) - len(b)) > 6 or a[0] != b[0]:
                    continue
                if fuzz.ratio(a, b) >= FUZZY_THRESHOLD:
                    union(a, b)
                    fuzzy_merges.append((a, b))
        if t == "Person":
            # "zuckerberg" -> "mark zuckerberg" when the surname is unambiguous
            full = [k for k in keys if " " in k]
            for k in keys:
                if " " not in k:
                    cands = [f for f in full if f.split()[-1] == k]
                    if len(cands) == 1:
                        union(cands[0], k)
                        fuzzy_merges.append((cands[0], k))

    clusters = defaultdict(list)
    for k in key_type:
        clusters[find(k)].append(k)

    mapping, merges = {}, []
    for root, keys in clusters.items():
        all_surfaces = Counter()
        for k in keys:
            all_surfaces.update(surfaces[k])
        # canonical name: most frequent surface form, then the longest
        canonical = sorted(all_surfaces.items(), key=lambda x: (-x[1], -len(x[0])))[0][0]
        ctype = key_type[root]
        cid = f"{ctype.lower()}:{root.replace(' ', '_')}"
        if len(all_surfaces) > 1:
            merges.append({"canonical": canonical, "type": ctype, "aliases": sorted(all_surfaces)})
        for k in keys:
            mapping[k] = (cid, canonical, ctype)

    raw_pairs = {(n, t) for n, t, _ in mentions}
    stats = {
        "mentions": sum(c for _, _, c in mentions),
        "distinct_surface_forms": len(raw_pairs),
        "after_normalisation": len(by_key),
        "type_conflicts_fixed": sum(1 for c in by_key.values() if len(c) > 1),
        "fuzzy_merges": len(fuzzy_merges),
        "resolved_entities": len(clusters),
    }
    stats["reduction_pct"] = round(100 * (1 - stats["resolved_entities"] / max(1, stats["distinct_surface_forms"])), 1)
    merges.sort(key=lambda m: -len(m["aliases"]))
    return mapping, stats, merges
