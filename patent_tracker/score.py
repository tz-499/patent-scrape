"""Two-stage relevance filter.

Stage 1 (cheap, streaming): keep a patent if it hits a topic's CPC prefix or keyword.
Stage 2 (ranking): TF-IDF cosine similarity between the patent text and the topic's
plain-English description, plus small boosts for CPC/keyword/assignee hits.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Topic:
    name: str
    description: str
    cpc_prefixes: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.cpc_prefixes = [compact(p) for p in self.cpc_prefixes]
        self.keywords = [k.lower() for k in self.keywords]


def compact(code: str) -> str:
    """'A61N 7/00' -> 'A61N7/00' so prefixes compare as plain strings."""
    return code.replace(" ", "").upper()


def patent_text(p: dict) -> str:
    return " ".join([p["title"], p["abstract"], p["first_claim"]])


def stage1(p: dict, topic: Topic) -> tuple[bool, int]:
    """Return (cpc_hit, keyword_hit_count) for one patent against one topic."""
    codes = [compact(c) for c in p["cpc"]]
    cpc_hit = any(c.startswith(prefix) for c in codes for prefix in topic.cpc_prefixes)
    hay = f"{p['title']} {p['abstract']}".lower()
    kw_hits = sum(1 for k in topic.keywords if k in hay)
    return cpc_hit, kw_hits


def is_candidate(p: dict, topics: list[Topic]) -> bool:
    return any(any(stage1(p, t)) for t in topics)


def rank(patents: list[dict], topics: list[Topic], cfg: dict) -> dict[str, list[dict]]:
    """Score candidates per topic; returns {topic name: top matches, best first}."""
    weights = {"cpc": 0.15, "keyword": 0.05, "assignee": 0.10, **cfg.get("weights", {})}
    min_score = cfg.get("min_score", 0.10)
    top_n = cfg.get("top_n", 15)
    watch = [w.lower() for w in cfg.get("watch_assignees", [])]
    out: dict[str, list[dict]] = {t.name: [] for t in topics}
    if not patents:
        return out

    docs = [patent_text(p) for p in patents]
    profiles = [f"{t.description} {' '.join(t.keywords)}" for t in topics]
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True, min_df=1)
    matrix = vec.fit_transform(docs + profiles)
    sims = cosine_similarity(matrix[: len(docs)], matrix[len(docs):])

    for j, topic in enumerate(topics):
        for i, p in enumerate(patents):
            cpc_hit, kw_hits = stage1(p, topic)
            if not (cpc_hit or kw_hits):
                continue
            watched = any(w in a.lower() for w in watch for a in p["assignees"])
            score = (
                float(sims[i, j])
                + weights["cpc"] * cpc_hit
                + weights["keyword"] * min(kw_hits, 4)
                + weights["assignee"] * watched
            )
            if score >= min_score:
                out[topic.name].append({**p, "topic": topic.name, "score": round(score, 4),
                                        "similarity": round(float(sims[i, j]), 4)})
        out[topic.name].sort(key=lambda m: m["score"], reverse=True)
        out[topic.name] = out[topic.name][:top_n]
    return out
