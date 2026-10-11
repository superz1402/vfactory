#!/usr/bin/env python3
"""Stage 2: research -> script plan.

Two modes:
  scenes    (default, short video): N scenes, 20-40 words each.
  chapters  (--minutes >= 3, long-form documentary): M chapters x ~2.5 min
            (~360-420 words each), generated chapter-by-chapter so the model
            keeps continuity (previous chapter summary is fed forward).

Every unit carries:
  narration       spoken text (FACT-disciplined to the research brief)
  role            cold_open|context|body|rise|turning_point|climax|
                  resolution|outro
  visual_queries  6-10 CONCRETE, entity-specific image searches. The queries
                  must match what the narration says at that point (say
                  BLACKPINK -> query BLACKPINK; say debut -> the debut moment).
  entities        key nouns mentioned, used later for shot/word alignment.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402

SYSTEM = (
    "You are a documentary scriptwriter. STRICT FACT RULES: use ONLY facts "
    "present in the SOURCES block. Never invent numbers, dates, quotes or "
    "statistics. If sources are thin, write in safe general terms. Narration "
    "is spoken text: clean sentences, no emojis, no markdown, no stage "
    "directions, no 'welcome back to the channel' filler."
)

SCENE_TEMPLATE = {
    "title": "short punchy video title",
    "logline": "one sentence what this video is",
    "scenes": [
        {"id": 1, "label": "hook", "narration": "2 spoken sentences max",
         "on_screen": "3-5 word caption", "visual_query": "concrete imageable scene"},
    ],
}

CH_TEMPLATE = {
    "id": 1,
    "title": "chapter title",
    "role": "cold_open",
    "narration": "360-420 spoken words, flowing documentary prose",
    "on_screen": "3-6 word caption",
    "visual_queries": ["8-10 concrete image search queries, one per idea",
                       "each query names the exact subject the narration mentions"],
    "entities": ["BLACKPINK", "Ahyeon"],
}

ARCS = [
    ("cold_open", "Cold open: drop the viewer into the most striking moment or "
                  "question of the story. No preamble."),
    ("context", "Set the world: origins, background, what came before."),
    ("body", "Develop the story chronologically; surface tension and stakes."),
    ("rise", "Escalate: momentum builds, obstacles appear."),
    ("turning_point", "The turn: the event that changed everything."),
    ("climax", "Peak of the arc: the defining triumph or crisis, told big."),
    ("resolution", "What followed: aftermath, meaning, reception."),
    ("outro", "Takeaway + forward-looking closing line. Land the theme."),
]


def _words(target_min):
    return int(target_min * 150)


def _gen_chapter(i, n, topic, style, brief, prev_summary, role, role_brief,
                 w_target, title_hint=""):
    q = f"""TOPIC: {topic}
STYLE: {style}

You are writing chapter {i} of {n} of a long-form documentary script.
CHAPTER ROLE: {role} — {role_brief}
TARGET LENGTH: about {w_target} spoken words (minimum {int(w_target*0.85)}).
{title_hint}

RULES:
- "narration" = {w_target} spoken words of flowing documentary prose. No lists,
  no headings, no stage directions. Vary sentence length; end chapters on a
  pull-forward line when role is not outro.
- "visual_queries": 8-10 image search queries. Each must be a CONCRETE visual
  (a person, group shot, stage, screen, place, object, crowd) that MATCHES the
  narration moment it illustrates. If the narration names a specific subject at
  a moment, one of the queries must show exactly that subject. Never generic
  stock abstractions. Include 1-2 queries for wide/atmosphere shots.
- "entities": the 3-8 proper nouns or key subjects spoken in this chapter, in
  order of first appearance.
- FACTS: only from SOURCES. Hedge what is uncertain ("reportedly", "around").
Return ONLY valid JSON matching exactly:
{json.dumps(CH_TEMPLATE, ensure_ascii=False)}

PREVIOUS CHAPTER SUMMARY (continue the flow, do not repeat):
{prev_summary or '(this is the first chapter)'}

SOURCES (use only these facts):
{brief[:9000]}"""
    ch = zai.chat_json(q, system=SYSTEM, timeout=420)
    if not ch or "narration" not in ch:
        raise RuntimeError(f"chapter {i}: model returned no narration")
    # word-count enforcement: append continuations until near target
    for _ in range(2):
        got = len(ch["narration"].split())
        if got >= int(w_target * 0.85):
            break
        more = zai.chat(
            f'Continue this documentary chapter with {int(w_target * 0.6)} more '
            f'spoken words. Do not repeat what is written; deepen the story '
            f'with concrete detail that fits the role ({role}). FACTS: only '
            f'from SOURCES below. Return ONLY the continuation prose, no '
            f'headings.\n\nCHAPTER SO FAR:\n{ch["narration"][-1500:]}\n\n'
            f'SOURCES:\n{brief[:6000]}',
            system=SYSTEM, timeout=420) or ""
        more = " ".join(more.split())
        # strip any accidental JSON fences/quotes
        more = more.strip().strip('`"').strip()
        if len(more.split()) < 40:
            break
        ch["narration"] = ch["narration"].rstrip() + " " + more
    ch.setdefault("visual_queries", [topic])
    ch.setdefault("entities", [])
    ch.setdefault("on_screen", ch.get("title", "")[:40])
    ch["role"] = role
    ch["id"] = i
    return ch


def run_scenes(run_dir, topic, style, n_scenes, region):
    out_path = os.path.join(run_dir, "02_script.json")
    research = json.load(open(os.path.join(run_dir, "01_research.json")))
    brief = research["brief"]
    shape = json.dumps(SCENE_TEMPLATE, ensure_ascii=False)
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
    plan.update({"topic": topic, "style": style, "region": region, "mode": "scenes"})
    json.dump(plan, open(out_path, "w"), ensure_ascii=False, indent=1)
    return plan


def run_chapters(run_dir, topic, style, minutes, region):
    out_path = os.path.join(run_dir, "02_script.json")
    research = json.load(open(os.path.join(run_dir, "01_research.json")))
    brief = research["brief"]

    n = max(3, min(16, round(minutes / 2.6)))
    w_target = _words(minutes / n)
    # role arc: cold_open -> middle progression -> outro
    middles = ["context"]
    arc_cycle = ["body", "body", "rise", "body", "turning_point", "body",
                 "climax", "resolution"]
    while len(middles) < n - 2:
        middles += arc_cycle
    roles = ["cold_open"] + middles[:n - 2] + ["outro"]

    plan = {"title": "", "logline": "", "mode": "chapters", "topic": topic,
            "style": style, "region": region, "minutes": minutes, "chapters": []}
    prev_summary = ""
    # ask once for title/logline from the brief
    head = zai.chat_json(
        f'TOPIC: {topic}\nGive a documentary title (max 60 chars, no clickbait '
        f'symbols) and a one-sentence logline. Return ONLY JSON: '
        f'{{"title": "...", "logline": "..."}}\nSOURCES:\n{brief[:3000]}',
        system=SYSTEM, timeout=240) or {}
    plan["title"] = (head.get("title") or topic)[:70]
    plan["logline"] = head.get("logline", "")

    for i, role in enumerate(roles, 1):
        role_brief = dict(ARCS)[role]
        hint = (f'The documentary title is "{plan["title"]}". '
                f'This is the FINAL chapter — close the story.' if role == "outro" else "")
        ch_path = os.path.join(run_dir, f"02_ch_{i:02d}.json")
        if os.path.exists(ch_path):
            ch = json.load(open(ch_path))
        else:
            ch = _gen_chapter(i, n, topic, style, brief, prev_summary,
                              role, role_brief, w_target, hint)
            ch["id"] = i
            json.dump(ch, open(ch_path, "w"), ensure_ascii=False, indent=1)
        plan["chapters"].append(ch)
        prev_summary = (f'Chapter {i} ({ch.get("title", role)}): '
                        f'{ch["narration"][:400]}...')
        print(f"  chapter {i}/{n} [{role}] {len(ch['narration'].split())} words",
              flush=True)
    json.dump(plan, open(out_path, "w"), ensure_ascii=False, indent=1)
    return plan


def run(run_dir, topic, style="documentary", n_scenes=7, region="us",
        minutes=0):
    if minutes and minutes >= 3:
        return run_chapters(run_dir, topic, style, int(minutes), region)
    return run_scenes(run_dir, topic, style, n_scenes, region)


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))  # 00_topic.json
    run(os.path.dirname(sys.argv[1]), d["topic"], d.get("style", "documentary"),
        d.get("n_scenes", 7), d.get("region", "us"), d.get("minutes", 0))
    print("script done:", d["topic"])
