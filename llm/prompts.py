# llm/prompts.py
from typing import List
from story_engine.io.schemas import ProjectConfig, Bible, ChapterOutline, ChapterSummary


def _format_bible_snippet(bible: Bible, pov: str) -> str:
    # Show only the bits that matter to the chapter to keep context small.
    # For now: just POV char + locations they’re in, plus any key side-characters.
    lines: List[str] = ["WORLD & CHARACTERS (summary):"]

    if pov in bible.characters:
        c = bible.characters[pov]
        lines.append(f"- POV: {c.name} — {c.bio}")
        lines.append(f"  Current state: {c.current_state}")

    # You can filter by tags like 'main', 'antagonist', 'supporting' etc.
    for name, c in bible.characters.items():
        if name == pov:
            continue
        if "main" in c.tags or "supporting" in c.tags:
            lines.append(f"- {c.name}: {c.bio}")
            lines.append(f"  State: {c.current_state}")

    lines.append("\nLOCATIONS:")
    for loc in bible.locations.values():
        lines.append(f"- {loc.name}: {loc.description}")

    # Items only if there aren’t too many
    if len(bible.items) <= 20:
        lines.append("\nITEMS:")
        for it in bible.items.values():
            owner = f" (owner: {it.owner})" if it.owner else ""
            lines.append(f"- {it.name}{owner}: {it.description} [{it.state}]")

    return "\n".join(lines)


def _format_story_so_far(summaries: List[ChapterSummary]) -> str:
    lines: List[str] = []
    for s in summaries:
        lines.append(f"CHAPTER {s.chapter_id} SUMMARY:")
        for bullet in s.bullet_summary:
            lines.append(f"- {bullet}")
        lines.append("")  # blank line
    return "\n".join(lines)


def build_chapter_prompt(
    cfg: ProjectConfig,
    bible: Bible,
    story_so_far: List[ChapterSummary],
    outline: ChapterOutline
) -> str:
    style_rules = "\n".join(f"- {rule}" for rule in cfg.style_rules)
    must_inc = "\n".join(f"- {m}" for m in outline.must_include)
    avoid = "\n".join(f"- {a}" for a in outline.avoid)
    beats = "\n".join(f"- {b}" for b in outline.beats)

    return f"""You are a long-form novel writing assistant.

STYLE:
- Tone: {cfg.tone}
{style_rules}

POINT OF VIEW:
- Third-person limited from {outline.pov}'s perspective.
- Stay inside their sensory experience and knowledge.

{_format_bible_snippet(bible, outline.pov)}

STORY SO FAR (brief summaries):
{_format_story_so_far(story_so_far)}

CURRENT CHAPTER OUTLINE:
- Chapter ID: {outline.chapter_id}
- Title: {outline.title}
- Target length: {outline.target_word_count} words

Beats:
{beats}

MUST INCLUDE (these events and details must appear):
{must_inc if must_inc else "- (none specified)"}

AVOID (do not do these):
{avoid if avoid else "- (none specified)"}

TASK:
Write the full chapter as continuous prose, around {outline.target_word_count} words.
Respect continuity with the story so far and the bible.
Do not break POV (no information {outline.pov} could not know).
Do not add new magic or technology outside what is implied.
Output only the chapter prose, no headings or meta commentary.
"""


def build_state_extractor_prompt(chapter_id: str, text: str) -> str:
    return f"""You are a story state extractor for a novel.

CHAPTER ID: {chapter_id}

CHAPTER TEXT:
{text}

TASK:
Analyse the chapter and return a single JSON object with this exact structure:

{{
  "bullet_summary": ["...", "..."],
  "character_updates": {{
    "Character Name": {{
      "location": "...",
      "physical": ["..."],
      "restraints": ["..."],
      "emotional": ["..."],
      "knowledge": ["..."],
      "relationship_to": {{"Other Name": "description"}}
    }}
  }},
  "location_updates": {{
    "Location Name": {{
      "description": "...",
      "tags": ["..."],
      "notes": ["..."]
    }}
  }},
  "item_updates": {{
    "Item Name": {{
      "owner": "Name or null",
      "location": "Location or null",
      "state": "new|intact|damaged|destroyed",
      "tags": ["..."]
    }}
  }}
}}

Guidelines:
- Only include characters/locations/items that change in this chapter.
- Keep bullet_summary to 3-7 short bullets.
- If something doesn't change, omit it from the updates.

Now return ONLY the JSON. No explanations.
"""
