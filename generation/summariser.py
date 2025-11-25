from __future__ import annotations

import json
import re
from typing import Any, Optional

from story_engine.io.schemas import ChapterSummary


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict:
    """
    Try to extract a JSON object from the model output.

    - First tries a ```json ... ``` fenced block.
    - Otherwise, takes from the first '{' to the last '}'.
    - If JSON is still invalid, progressively trims from the end
      until parse succeeds or we give up.

    Raises ValueError if nothing usable can be found.
    """
    # 1) Look for ```json ... ``` first
    fence_match = re.search(r"```json(.*)```", text, re.DOTALL | re.IGNORECASE)
    candidate: Optional[str] = None

    if fence_match:
        candidate = fence_match.group(1).strip()
    else:
        # 2) Fallback: first '{' to last '}'
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in model output")
        candidate = text[start : end + 1]

    # 3) Try parsing; if it fails, trim from the end and try again
    s = candidate.strip()
    while s:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # Trim last line or last char, try again
            last_nl = s.rfind("\n")
            if last_nl == -1 or len(s) - last_nl < 4:
                s = s[:-1]
            else:
                s = s[:last_nl].rstrip()

    raise ValueError("Could not parse JSON from model output")


# ---------------------------------------------------------------------------
# Summariser
# ---------------------------------------------------------------------------


class Summariser:
    """
    Handles chapter summaries and applies them to the story bible.

    This version is defensive:

    - Handles 'summary' / 'short_summary' from the LLM.
    - Ensures required fields like character_updates / location_updates /
      item_updates / bullet_summary exist.
    - Filters out unknown keys before constructing ChapterSummary.
    - Is robust to None / weird values inside *_updates.
    - Treats the bible as a simple dict structure.
    """

    def __init__(self, repo: Any, llm: Any):
        self.repo = repo
        self.llm = llm

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def build_summary_prompt(self, chapter_id: str, chapter_text: str) -> str:
        """
        Prompt that encourages valid JSON aligned with ChapterSummary.

        Adjust if needed, but keep the JSON shape consistent with your
        ChapterSummary schema.
        """
        cfg = self.repo.load_project_config()
        title = getattr(cfg, "title", "Untitled Story")

        return f"""You are helping maintain a structured story bible for a long-form novel.

Summarise chapter "{chapter_id}" of the story "{title}" into a single JSON object
with EXACTLY this shape (you may omit individual keys inside the sub-objects,
but the top-level keys must all exist):

{{
  "chapter_id": "{chapter_id}",
  "bullet_summary": [
    "short bullet 1",
    "short bullet 2"
  ],
  "character_updates": {{
    "Character Name": {{
      "bio": "optional short update to their bio",
      "location": "where they are now",
      "tags": ["optional", "tags"]
    }}
  }},
  "location_updates": {{
    "Place Name": {{
      "description": "short description or change",
      "tags": ["optional", "tags"]
    }}
  }},
  "item_updates": {{
    "Item Name": {{
      "description": "short description or change",
      "location": "where the item currently is",
      "tags": ["optional", "tags"]
    }}
  }}
}}

Rules:
- Output ONLY JSON, no prose, no markdown fences.
- bullet_summary MUST be a list (can be empty).
- *_updates MUST be objects (can be empty).
- If you have no updates for a category, use an empty object: {{}}.

Chapter text:
\"\"\"{chapter_text}\"\"\""""

    # ------------------------------------------------------------------
    # Main: summarise a single chapter
    # ------------------------------------------------------------------

    def summarise_chapter(self, chapter_id: str, apply_to_bible: bool = True) -> ChapterSummary:
        """
        Call the LLM, parse JSON, and safely build a ChapterSummary.

        - Accepts 'short_summary' or 'summary' from the model.
        - Ensures required fields like location_updates/item_updates exist.
        - Filters out unknown keys before constructing ChapterSummary.
        - Never crashes on bad JSON: falls back to a minimal summary.

        apply_to_bible:
          - True: also updates the bible immediately.
          - False: just returns the ChapterSummary.
        """
        # 1) Get chapter text
        text = (
            self.repo.load_chapter_text(chapter_id, kind="final")
            or self.repo.load_chapter_text(chapter_id, kind="draft")
        )
        if not text:
            raise ValueError(f"No text found for chapter {chapter_id}")

        # 2) Build prompt + call LLM
        prompt = self.build_summary_prompt(chapter_id, text)
        raw = self.llm.complete(prompt, max_tokens=(32*1024), temperature=0.3)

        # 3) Parse JSON (robustly)
        try:
            data = _extract_json(raw)
        except ValueError as e:
            # Fallback: don't crash pipeline; create a very minimal summary
            print(f"[WARN] Failed to parse JSON summary for {chapter_id}: {e}")
            data = {
                "chapter_id": chapter_id,
                "bullet_summary": [
                    "Summary unavailable due to JSON parse error."
                ],
                "character_updates": {},
                "location_updates": {},
                "item_updates": {},
            }

        # 4) Normalise 'short_summary' -> 'summary' if needed
        if "short_summary" in data and "summary" not in data:
            data["summary"] = data.pop("short_summary")

        # Ensure chapter_id is set
        data.setdefault("chapter_id", chapter_id)

        # 5) Work out which fields ChapterSummary actually accepts
        if hasattr(ChapterSummary, "__dataclass_fields__"):
            allowed = set(ChapterSummary.__dataclass_fields__.keys())
        elif hasattr(ChapterSummary, "model_fields"):  # pydantic v2
            allowed = set(ChapterSummary.model_fields.keys())
        elif hasattr(ChapterSummary, "__fields__"):    # pydantic v1
            allowed = set(ChapterSummary.__fields__.keys())
        else:
            allowed = set(data.keys())  # very unlikely, but safe

        # 6) Ensure required *_updates dicts exist if they are allowed fields
        for key in ("character_updates", "location_updates", "item_updates"):
            if key in allowed and key not in data:
                data[key] = {}

        # 7) Handle 'summary' if ChapterSummary doesn't have that field
        if "summary" in data and "summary" not in allowed:
            if "bullet_summary" in allowed:
                bullets = data.get("bullet_summary") or []
                if not isinstance(bullets, list):
                    bullets = [str(bullets)]
                if not bullets:
                    bullets = [str(data["summary"])]
                data["bullet_summary"] = bullets
            # Remove summary so it doesn't break the constructor
            data.pop("summary", None)

        # 8) Default bullet_summary if needed
        if "bullet_summary" in allowed and "bullet_summary" not in data:
            data["bullet_summary"] = []

        # 9) Drop any remaining unknown keys
        filtered = {k: v for k, v in data.items() if k in allowed}

        # 10) Now we can safely construct ChapterSummary
        summary = ChapterSummary(**filtered)

        # 11) Persist + (optionally) update bible
        if hasattr(self.repo, "save_chapter_summary"):
            self.repo.save_chapter_summary(chapter_id, filtered)

        if apply_to_bible:
            self.apply_summary_to_bible(summary)

        return summary

    # ------------------------------------------------------------------
    # Apply summary to bible (bible as dict)
    # ------------------------------------------------------------------

    def apply_summary_to_bible(
        self,
        summary: ChapterSummary,
        bible: Optional[dict] = None,
    ) -> dict:
        """
        Merge a ChapterSummary into the story bible.

        - Defensive against None and non-dict values in *_updates.
        - Bible is just a dict with keys:
            "characters", "locations", "items"
        """
        # Load bible if not provided
        if bible is None:
            bible = self.repo.load_bible()
        if bible is None or not isinstance(bible, dict):
            bible = {}

        characters = bible.setdefault("characters", {})
        locations = bible.setdefault("locations", {})
        items = bible.setdefault("items", {})

        # --- CHARACTER UPDATES ---
        char_updates = getattr(summary, "character_updates", {}) or {}
        if not isinstance(char_updates, dict):
            char_updates = {}

        for name, upd in char_updates.items():
            if upd is None:
                continue
            if not isinstance(upd, dict):
                upd = {"bio": str(upd)}

            bio = upd.get("bio")
            location = upd.get("location")
            tags = upd.get("tags") or []

            rec = characters.get(name) or {}
            rec.setdefault("name", name)

            if bio:
                rec["bio"] = bio
            if tags:
                rec["tags"] = tags
            if location:
                rec["location"] = location

            characters[name] = rec

        # --- LOCATION UPDATES ---
        loc_updates = getattr(summary, "location_updates", {}) or {}
        if not isinstance(loc_updates, dict):
            loc_updates = {}

        for name, upd in loc_updates.items():
            if upd is None:
                continue
            if not isinstance(upd, dict):
                upd = {"description": str(upd)}

            desc = upd.get("description")
            tags = upd.get("tags") or []

            rec = locations.get(name) or {}
            rec.setdefault("name", name)

            if desc:
                rec["description"] = desc
            if tags:
                rec["tags"] = tags

            locations[name] = rec

        # --- ITEM UPDATES ---
        item_updates = getattr(summary, "item_updates", {}) or {}
        if not isinstance(item_updates, dict):
            item_updates = {}

        for name, upd in item_updates.items():
            if upd is None:
                continue
            if not isinstance(upd, dict):
                upd = {"description": str(upd)}

            desc = upd.get("description")
            loc = upd.get("location")
            tags = upd.get("tags") or []

            rec = items.get(name) or {}
            rec.setdefault("name", name)

            if desc:
                rec["description"] = desc
            if tags:
                rec["tags"] = tags
            if loc:
                rec["location"] = loc

            items[name] = rec

        # Save and return
        self.repo.save_bible(bible)
        return bible

    # ------------------------------------------------------------------
    # Rebuild state (bible) from chapter summaries
    # ------------------------------------------------------------------

    def rebuild_state_from(self, up_to_chapter_id: Optional[str] = None) -> dict:
        """Rebuild the bible from scratch by re-summarising chapters in order.

        - Starts from an empty bible dict.
        - For each chapter in project.chapter_order:
            - If a saved summary exists, use it.
            - Otherwise, call summarise_chapter(apply_to_bible=False).
        - Applies each summary into the in-memory bible.
        - Stops when it reaches up_to_chapter_id (if provided).
        - Writes the rebuilt bible via repo.save_bible(bible).
        """
        cfg = self.repo.load_project_config()
        bible: dict = {"characters": {}, "locations": {}, "items": {}}

        for cid in cfg.chapter_order:
            # Try to load an existing summary if the repo supports it
            data = None
            if hasattr(self.repo, "load_chapter_summary"):
                data = self.repo.load_chapter_summary(cid)

            if data is not None:
                try:
                    summary = ChapterSummary(**data)
                except Exception:
                    summary = self.summarise_chapter(cid, apply_to_bible=False)
            else:
                summary = self.summarise_chapter(cid, apply_to_bible=False)

            bible = self.apply_summary_to_bible(summary, bible)

            if up_to_chapter_id and cid == up_to_chapter_id:
                break

        self.repo.save_bible(bible)
        return bible

        # ------------------------------------------------------------------
    # Rebuild timeline from chapter summaries
    # ------------------------------------------------------------------

    def rebuild_timeline(self) -> dict:
        """
        Rebuild a simple timeline from chapter summaries.

        Timeline shape (saved to timeline.json via repo.save_timeline):

        {
          "events": [
            {
              "chapter_id": "ch01",
              "index": 0,
              "title": "Optional chapter title",
              "bullets": [
                "bullet summary 1",
                "bullet summary 2"
              ]
            },
            ...
          ]
        }

        - Uses saved chapter summaries if available.
        - Otherwise calls summarise_chapter(apply_to_bible=False).
        """
        cfg = self.repo.load_project_config()
        timeline: dict = {"events": []}

        for idx, cid in enumerate(cfg.chapter_order):
            # Try to load existing summary JSON if the repo supports it
            data = None
            if hasattr(self.repo, "load_chapter_summary"):
                data = self.repo.load_chapter_summary(cid)

            if data is not None:
                try:
                    summary = ChapterSummary(**data)
                except Exception:
                    summary = self.summarise_chapter(cid, apply_to_bible=False)
            else:
                summary = self.summarise_chapter(cid, apply_to_bible=False)

            # Optional: use chapter outline to get a nicer title
            outline = None
            if hasattr(self.repo, "load_chapter_outline"):
                outline = self.repo.load_chapter_outline(cid)

            title = cid
            if outline:
                title = (
                    outline.get("title")
                    or outline.get("name")
                    or title
                )

            bullets = getattr(summary, "bullet_summary", []) or []
            if not isinstance(bullets, list):
                bullets = [str(bullets)]

            event = {
                "chapter_id": cid,
                "index": idx,
                "title": title,
                "bullets": bullets,
            }
            timeline["events"].append(event)

        # Persist via repo, if supported
        if hasattr(self.repo, "save_timeline"):
            self.repo.save_timeline(timeline)

        return timeline
