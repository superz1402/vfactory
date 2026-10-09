#!/usr/bin/env python3
"""Stage 1: topic -> research brief. Multi-angle web search, deduped, compacted."""
import json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402


def angle_queries(topic):
    """3 search angles around the topic (facts/history/reception)."""
    return [
        f"{topic} history timeline key events",
        f"{topic} achievements milestones facts",
        f"{topic} 2025 2026 latest news",
    ]


def run(run_dir, topic, region="us", max_sources=24):
    out_path = os.path.join(run_dir, "01_research.json")
    queries = angle_queries(topic)
    sources, seen = [], set()
    for q in queries:
        for item in zai.search(q, num=8):
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append({
                "title": ((item.get("title") or item.get("name") or ""))[:160],
                "url": url,
                "snippet": re.sub(r"\s+", " ", (item.get("snippet") or item.get("content") or item.get("description") or ""))[:400],
                "query": q,
            })
    sources = sources[:max_sources]
    brief = "\n".join(f"- [{s['title']}] {s['snippet']}" for s in sources) or "NO EXTERNAL SOURCES FOUND"
    data = {"topic": topic, "queries": queries, "region": region,
            "source_count": len(sources), "sources": sources, "brief": brief[:12000]}
    json.dump(data, open(out_path, "w"), ensure_ascii=False, indent=1)
    return data


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))          # 00_topic.json
    run(os.path.dirname(sys.argv[1]), d["topic"], d.get("region", "us"))
    print("research done:", d["topic"])
