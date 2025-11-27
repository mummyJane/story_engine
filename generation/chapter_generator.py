from __future__ import annotations

import json
from typing import Any, Dict

from story_engine.io.project_repo import ProjectRepo


class ChapterGenerator:
    """
    Generate chapter prose from chapter outlines + story bible.

    Works with:
      - repo.load_project_config()
      - repo.load_chapter_outline(chapter_id)
      - repo.load_bible()       -> dict with "characters"/"locations"/"items"
      - repo.save_chapter_text(chapter_id, kind, text)
      - llm.complete(prompt, max_tokens=..., temperature=...)
    """

    def __init__(self, repo: ProjectRepo, llm: Any):
        self.repo = repo
        self.llm = llm

    # ------------------------------------------------------------------
    # Helpers to read bible sections safely
    # ------------------------------------------------------------------

    @staticmethod
    def _get_bible_section(bible: Any, key: str) -> Dict[str, Any]:
        """
        Return bible[key] if bible is a dict, or getattr(bible, key, {}) if
        bible is an object; always returns a dict.
        """
        if isinstance(bible, dict):
            sec = bible.get(key, {}) or {}
        else:
            sec = getattr(bible, key, {}) or {}
        if not isinstance(sec, dict):
            sec = {}
        return sec

    @staticmethod
    def _summarise_characters(chars: Dict[str, Any]) -> str:
        """
        Turn the bible's characters dict into a compact bullet summary.
        """
        if not chars:
            return "No prior character entries yet."

        lines = []
        for name, rec in chars.items():
            if isinstance(rec, dict):
                bio = rec.get("bio", "") or ""
                location = rec.get("location", "") or ""
                tags = rec.get("tags", []) or []
            else:
                bio = getattr(rec, "bio", "") or ""
                location = getattr(rec, "location", "") or ""
                tags = getattr(rec, "tags", []) or []

            tag_str = ", ".join(tags) if tags else ""
            parts = []
            if bio:
                parts.append(bio)
            if location:
                parts.append(f"Location: {location}")
            if tag_str:
                parts.append(f"Tags: {tag_str}")

            if parts:
                lines.append(f"- {name}: " + " | ".join(parts))
            else:
                lines.append(f"- {name}")
        return "\n".join(lines)

    @staticmethod
    def _summarise_locations(locs: Dict[str, Any]) -> str:
        """
        Turn the bible's locations dict into a compact bullet summary.
        """
        if not locs:
            return "No prior location entries yet."

        lines = []
        for name, rec in locs.items():
            desc = ""
            tags = []
            if isinstance(rec, dict):
                desc = rec.get("description", "") or ""
                tags = rec.get("tags", []) or []
            else:
                desc = getattr(rec, "description", "") or ""
                tags = getattr(rec, "tags", []) or []

            tag_str = ", ".join(tags) if tags else ""
            parts = []
            if desc:
                parts.append(desc)
            if tag_str:
                parts.append(f"Tags: {tag_str}")

            if parts:
                lines.append(f"- {name}: " + " | ".join(parts))
            else:
                lines.append(f"- {name}")
        return "\n".join(lines)

    @staticmethod
    def _summarise_items(items: Dict[str, Any]) -> str:
        """
        Turn the bible's items dict into a compact bullet summary.
        """
        if not items:
            return "No prior item entries yet."

        lines = []
        for name, rec in items.items():
            if isinstance(rec, dict):
                desc = rec.get("description", "") or ""
                location = rec.get("location", "") or ""
                tags = rec.get("tags", []) or []
            else:
                desc = getattr(rec, "description", "") or ""
                location = getattr(rec, "location", "") or ""
                tags = getattr(rec, "tags", []) or []

            tag_str = ", ".join(tags) if tags else ""
            parts = []
            if desc:
                parts.append(desc)
            if location:
                parts.append(f"Location: {location}")
            if tag_str:
                parts.append(f"Tags: {tag_str}")

            if parts:
                lines.append(f"- {name}: " + " | ".join(parts))
            else:
                lines.append(f"- {name}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Prompt builder – uses BOTH bible and full outline JSON
    # ------------------------------------------------------------------

    def build_prompt(self, chapter_id: str) -> str:
        """
        Build a prompt for the LLM using:

          - project config (title, tone)
          - chapter outline (full JSON)
          - story bible (characters, locations, items)

        This is deliberately tolerant of missing fields.
        """
        cfg = self.repo.load_project_config()
        outline = self.repo.load_chapter_outline(chapter_id) or {}
        bible = self.repo.load_bible() or {}

        title = getattr(cfg, "title", "Untitled Story")
        tone = getattr(cfg, "tone", "") or ""

        chapter_title = outline.get("title", chapter_id)
        chapter_goal = (
            outline.get("goal")
            or outline.get("summary")
            or outline.get("outline")
            or outline.get("short_summary")
            or ""
        )
        chapter_notes = outline.get("notes", "")

        # Full outline as JSON so the model can see *everything*
        outline_json = json.dumps(outline, indent=2, ensure_ascii=False)

        # Bible sections (dicts)
        chars = self._get_bible_section(bible, "characters")
        locs = self._get_bible_section(bible, "locations")
        items = self._get_bible_section(bible, "items")

        chars_text = self._summarise_characters(chars)
        locs_text = self._summarise_locations(locs)
        items_text = self._summarise_items(items)

        tone_line = (
            f"Overall tone: {tone}"
            if tone
            else "Overall tone: default narrative style."
        )

        # NOTE: no Markdown code fences here; just plain text so nothing
        # weird happens when copying or logging.
        prompt = (
            "You are writing a chapter of a long-form novel.\n\n"
            f'Story: "{title}"\n'
            f"{tone_line}\n\n"
            f"Chapter ID: {chapter_id}\n"
            f"Chapter title: {chapter_title}\n\n"
            "High-level goal / outline for this chapter (plain language):\n"
            f"{chapter_goal or '(No short outline provided yet.)'}\n\n"
            "Additional chapter notes:\n"
            f"{chapter_notes or '(No extra notes.)'}\n\n"
            "Full structured outline JSON for this chapter "
            "(for you to follow; do NOT echo this JSON back directly):\n"
            f"{outline_json}\n\n"
            "Story bible — main characters:\n"
            f"{chars_text}\n\n"
            "Story bible — key locations:\n"
            f"{locs_text}\n\n"
            "Story bible — important items:\n"
            f"{items_text}\n\n"
            "Write the full prose for this chapter as continuous narrative text.\n\n"
            "Requirements:\n"
            "- You MUST respect the structured outline JSON above: all important beats,\n"
            "  events, and constraints in that outline should be reflected in the chapter.\n"
            "- You MUST remain consistent with the story bible when using characters,\n"
            "  locations, and items (names, relationships, locations, etc.).\n"
            "- You MAY add extra detail (sensory detail, inner thoughts, transitions)\n"
            "  as long as it does not contradict the outline or bible.\n"
            "- Use a natural third-person past-tense style.\n"
            "- Do NOT output JSON, bullet lists, or commentary. Output only the story text.\n"
        )
        return prompt

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate_chapter(self, chapter_id: str, kind: str = "draft") -> str:
        prompt = self.build_prompt(chapter_id)

        # Use model-aware max_tokens from the client
        text = self.llm.complete(
            prompt,
            # no explicit max_tokens -> client picks largest safe value
            temperature=0.75,
        )

        self.repo.save_chapter_text(chapter_id, kind, text)
        return text
