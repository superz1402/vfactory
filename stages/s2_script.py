#!/usr/bin/env python3
"""Stage 2: research -> scene plan JSON (title + narration scenes + visual queries).
FACT discipline: the LLM must only use supplied sources; unknowns get hedged."""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402

SYSTEM = (
    "You are a documentary scriptwriter for short-form YouTube videos. "
    "STRICT FACT RULES: use ONLY facts present in the SOURCES block. "
    "Never invent numbers, dates, quotes or statistics. If sources are thin, "
    "write in safe general terms. Narration is spoken text: clean sentences, "
    "no emojis, no markdown, no stage directions."
)

TEMPLATE = {
    "title": "short punchy video title",
    "logline": "one sentence what this video is",
    "scenes": [
        {"id": 1, "label": "hook", "narration": "2 spoken sentences max",
         "on_screen": "3-5 word caption", "visual_query": "concrete imageable scene"},
    ],
}


def run(run_dir, topic, style="documentary", n_scenes=7, region="us"):
    out_path = os.path.join(run_dir, "02_script.json")
    research = json.load(open(os.path.join(run_dir, "01_research.json")))
    brief = research["brief"]

    shape = json.dumps(TEMPLATE, ensure_ascii=False)
    prompt = f"""TOPIC: {topic}
STYLE: {style}
SCENES: exactly {n_scenes} — id 1 is a HOOK (question or bold statement), ids 2..{n_scenes-1} are the body (chronological or thematic), id {n_scenes} is an OUTRO (takeaway + forward-looking line).
Each scene: "narration" = 20-40 spoken words; "on_screen" = 3-6 word caption; "visual_query" = a concrete visual image search query in English (a place, person-at-work, object, crowd, stage, screen — NOT abstract text).
Return ONLY valid JSON matching this shape exactly, no commentary:
{shape}

SOURCES (use only these facts):
{brief[:9000]}"""

    plan = zai.chat_json(prompt, system=SYSTEM, timeout=420)
    if not plan or "scenes" not in plan or not isinstance(plan["scenes"], list) or len(plan["scenes"]) < 3:
        raise RuntimeError("script model did not return a valid scene plan")
    for i, sc in enumerate(plan["scenes"], 1):
        sc["id"] = i
        for k in ("label", "narration", "on_screen", "visual_query"):
            sc.setdefault(k, "")
        sc["narration"] = sc["narration"].strip() or topic
        sc["visual_query"] = sc["visual_query"].strip() or topic
    plan["topic"] = topic
    plan["style"] = style
    plan["region"] = region
    json.dump(plan, open(out_path, "w"), ensure_ascii=False, indent=1)
    return plan


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))  # 00_topic.json
    run(os.path.dirname(sys.argv[1]), d["topic"], d.get("style", "documentary"),
        d.get("n_scenes", 7), d.get("region", "us"))
    print("script done:", d["topic"])
