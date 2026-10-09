#!/usr/bin/env python3
"""Stage 2 (v2): research -> documentary BEAT plan.

Documentary grammar (learned from BPM Stories / KOOKIELIT metrics, see
research/DESIGN_V2.md): the video is a chain of 12-16 BEATS of 8-14s; each
beat's narration is 1-3 spoken sentences; each beat gets its own visual
intent (2-4 concrete shots) so the render cuts every 2.5-5s.
FACT discipline unchanged: only facts from SOURCES; hedge when thin.
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402

SYSTEM = (
    "You are a documentary scriptwriter for YouTube video essays in the style of "
    "BPM Stories and KOOKIELIT K-pop documentaries. "
    "STRICT FACT RULES: use ONLY facts present in the SOURCES block. "
    "Never invent numbers, dates, quotes or statistics. If sources are thin, "
    "write in safe general terms. Narration is spoken text: clean sentences, "
    "no emojis, no markdown, no stage directions. Keep a confident essay voice."
)

TEMPLATE = {
    "title": "short punchy video title",
    "logline": "one sentence what this video is",
    "chapters": [
        {"id": "hook", "card_text": "2-4 word title card or EMPTY for none"}
    ],
    "beats": [
        {"id": 1, "chapter": "hook",
         "narration": "1-3 spoken sentences (15-40 words)",
         "on_screen": "3-6 word elegant overlay text, or empty string for none",
         "mood": "dark|tense|hopeful|triumphant|reflective|energetic",
         "visual_intent": ["concrete shot description 1 (a person, stage, crowd, city, object)",
                           "concrete shot description 2",
                           "concrete shot description 3"]}
    ],
}


def run(run_dir, topic, style="documentary", target_seconds=165, region="us"):
    out_path = os.path.join(run_dir, "02_script.json")
    research = json.load(open(os.path.join(run_dir, "01_research.json")))
    brief = research["brief"]

    n_beats = max(10, min(16, int(target_seconds / 11.5)))
    shape = json.dumps(TEMPLATE, ensure_ascii=False)
    prompt = f"""TOPIC: {topic}
STYLE: {style}
TARGET RUNTIME: about {target_seconds} seconds of narration.

Write a documentary in BEATS. Exactly {n_beats} beats.
Beat 1 = cold-open HOOK: a bold, specific statement or question about the topic.
Beats 2..{n_beats-1} = the story: origins -> rise -> obstacles/controversy -> milestones -> what it means. Group them into 3-5 "chapters" (id strings like hook/origins/rise/obstacle/legacy). Chapters get optional elegant title-card text (card_text), most chapters have EMPTY card_text — only 2-3 cards in the whole video.
Beat {n_beats} = OUTRO: takeaway + forward-looking line.
Rules:
- "narration": 15-40 spoken words. Vary rhythm. No lists. No rhetorical padding.
- "on_screen": mostly empty; put a short text on at most 5 beats total (names, dates, records — like "November 15, 2023").
- "mood": one of dark|tense|hopeful|triumphant|reflective|energetic; the HOOK is usually dark or tense; outro reflective or hopeful.
- "visual_intent": 2-4 CONCRETE shot descriptions for this beat (closeup faces, stage lights, choreography, crowd lightsticks, city skyline, practice room mirror, magazine covers). For a K-pop idol documentary prefer: performance moments, live-vocal closeups, concert crowds, Seoul city b-roll, backstage moments. Shot 1 should be the most striking.
Return ONLY valid JSON matching this shape exactly, no commentary:
{shape}

SOURCES (use only these facts):
{brief[:9000]}"""

    plan = zai.chat_json(prompt, system=SYSTEM, timeout=420)
    if not plan or "beats" not in plan or not isinstance(plan["beats"], list) or len(plan["beats"]) < 8:
        raise RuntimeError("script model did not return a valid beat plan")
    for i, b in enumerate(plan["beats"], 1):
        b["id"] = i
        b.setdefault("chapter", "story")
        b.setdefault("on_screen", "")
        b.setdefault("mood", "dark")
        b.setdefault("visual_intent", [])
        b["narration"] = str(b["narration"]).strip() or topic
        if isinstance(b["visual_intent"], str):
            b["visual_intent"] = [b["visual_intent"]]
    # chapter card dedupe: at most 3 cards
    cards = [c for c in plan.get("chapters", []) if isinstance(c, dict) and c.get("card_text")]
    plan["chapters"] = cards[:3]
    plan["topic"] = topic
    plan["style"] = style
    plan["region"] = region
    json.dump(plan, open(out_path, "w"), ensure_ascii=False, indent=1)
    return plan


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))  # 00_topic.json
    run(os.path.dirname(sys.argv[1]), d["topic"], d.get("style", "documentary"),
        d.get("target_seconds", 165), d.get("region", "us"))
    print("script done:", d["topic"])
