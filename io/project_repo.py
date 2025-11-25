from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schemas import ProjectConfig  # adjust if your ProjectConfig is elsewhere


@dataclass
class ChapterVersionInfo:
    """Metadata about a single versioned chapter text file."""
    chapter_id: str
    kind: str          # "draft" or "final"
    version: int
    path: Path
    mtime: float


class ProjectRepo:
    """
    Disk I/O helper for a single story project.

    Project layout (relative to `root`):

      project.json
      chapters/
        ch01_outline.json
        ch01_draft_v1.txt
        ch01_draft_v2.txt
        ch01_final_v1.txt
        ...
      summaries/
        ch01_summary.json
      bible/
        bible.json
      timeline.json
      notes.md (handled directly by web app)
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    # ------------------------------------------------------------------
    # Generic JSON helpers
    # ------------------------------------------------------------------

    def _load_json(self, rel_path: str, default: Any = None) -> Any:
        """
        Load JSON from a path relative to the project root.
        Returns `default` if the file does not exist.
        """
        path = self.root / rel_path
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save_json(self, rel_path: str, data: Any) -> None:
        """
        Save JSON to a path relative to the project root.
        """
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Project config
    # ------------------------------------------------------------------

    def load_project_config(self) -> ProjectConfig:
        """
        Load project.json and return a ProjectConfig object.
        If it doesn't exist, create a minimal default config.
        """
        data = self._load_json("project.json", default=None)
        if data is None:
            # Minimal default; adjust fields to match your ProjectConfig
            return ProjectConfig(
                title="Untitled",
                author="",
                chapter_order=[],
                style_rules=[],
                tone="",
                model_name=None,
            )
        # data -> ProjectConfig, regardless of pydantic/dataclass
        return ProjectConfig(**data)

    def save_project_config(self, cfg: Any) -> None:
        """
        Save the project config back to project.json.

        Accepts either:
          - a ProjectConfig instance, or
          - a plain dict with the same shape.
        """
        # Avoid circular import at module import time
        from .schemas import ProjectConfig as _PC  # type: ignore

        if isinstance(cfg, _PC):
            # pydantic v2
            if hasattr(cfg, "model_dump"):
                data = cfg.model_dump()
            # pydantic v1
            elif hasattr(cfg, "dict"):
                data = cfg.dict()
            # dataclass
            elif hasattr(cfg, "__dataclass_fields__"):
                data = asdict(cfg)
            else:
                data = dict(cfg)
        else:
            data = cfg

        self._save_json("project.json", data)

    # ------------------------------------------------------------------
    # Chapter outlines
    # ------------------------------------------------------------------

    def load_chapter_outline(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        """Load the outline JSON for a chapter.

        Behaviour:
        - First, try canonical file: chapters/{chapter_id}_outline.json
        - If missing, look for legacy/versioned files:
          chapters/{chapter_id}_outline_vN.json and pick the highest N.
          If found, load it and also write it back to the canonical name.
        """
        chapters_dir = self.root / "chapters"
        path = chapters_dir / f"{chapter_id}_outline.json"
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                # fall through to legacy lookup
                pass

        # look for versioned files
        if not chapters_dir.exists():
            return None

        pattern = re.compile(
            rf"^{re.escape(chapter_id)}_outline_v(\d+)\.json$",
            re.IGNORECASE,
        )

        best_path = None
        best_v = -1
        for p in chapters_dir.iterdir():
            if not p.is_file():
                continue
            m = pattern.match(p.name)
            if not m:
                continue
            try:
                v = int(m.group(1))
            except ValueError:
                continue
            if v > best_v:
                best_v = v
                best_path = p

        if best_path is None:
            return None

        # 3) Load the best legacy outline and migrate it to the canonical name
        try:
            with best_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        # save canonical copy for future use
        self._save_json(f"chapters/{chapter_id}_outline.json", data)
        return data


    def save_chapter_outline(self, chapter_id: str, outline: Dict[str, Any]) -> None:
        """Save the outline JSON for a chapter with simple versioning.

        - The current outline is always stored in chapters/{chapter_id}_outline.json
        - Previous versions are stored as chapters/{chapter_id}_outline_vN.json
          where N is a monotonically increasing integer.
        - If the content has not changed compared to the last saved version,
          no new version file is created.
        """
        chapters_dir = self.root / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        canonical = chapters_dir / f"{chapter_id}_outline.json"
        new_text = json.dumps(outline, indent=2, ensure_ascii=False, sort_keys=True)

        latest_version = 0
        if canonical.exists():
            try:
                existing_text = canonical.read_text(encoding="utf-8")
            except Exception:
                existing_text = ""
            if existing_text == new_text:
                # nothing changed; keep existing version
                return

            # compute highest existing version
            pattern = re.compile(
                rf"^{re.escape(chapter_id)}_outline_v(\d+)\.json$",
                re.IGNORECASE,
            )
            for p in chapters_dir.iterdir():
                if not p.is_file():
                    continue
                m = pattern.match(p.name)
                if not m:
                    continue
                try:
                    v = int(m.group(1))
                except ValueError:
                    continue
                if v > latest_version:
                    latest_version = v

        next_v = latest_version + 1
        version_path = chapters_dir / f"{chapter_id}_outline_v{next_v}.json"
        version_path.write_text(new_text, encoding="utf-8")
        canonical.write_text(new_text, encoding="utf-8")

    # ------------------------------------------------------------------
    # Chapter text (versioned)
    # ------------------------------------------------------------------

    def list_chapter_versions(
        self,
        chapter_id: str,
        kind: Optional[str] = None,
    ) -> List[ChapterVersionInfo]:
        """
        Scan the chapters folder and list all known versions of this chapter.
        Assumes filenames like ch01_draft_v1.txt, ch01_final_v2.txt.
        """
        chapters_dir = self.root / "chapters"
        if not chapters_dir.exists():
            return []

        pattern = re.compile(
            rf"^{re.escape(chapter_id)}_(draft|final)_v(\d+)\.txt$",
            re.IGNORECASE,
        )

        versions: List[ChapterVersionInfo] = []
        for path in chapters_dir.iterdir():
            if not path.is_file():
                continue
            m = pattern.match(path.name)
            if not m:
                continue
            k = m.group(1).lower()
            v = int(m.group(2))
            if kind and k != kind:
                continue
            stat = path.stat()
            versions.append(
                ChapterVersionInfo(
                    chapter_id=chapter_id,
                    kind=k,
                    version=v,
                    path=path,
                    mtime=stat.st_mtime,
                )
            )

        versions.sort(key=lambda info: info.version)
        return versions

    def load_chapter_text_version(
        self,
        chapter_id: str,
        kind: str,
        version: int,
    ) -> str:
        """
        Load a specific version of a chapter.
        """
        path = self.root / "chapters" / f"{chapter_id}_{kind}_v{version}.txt"
        if not path.exists():
            raise FileNotFoundError(path)
        return path.read_text(encoding="utf-8")

    def load_chapter_text(self, chapter_id: str, kind: str = "draft") -> str:
        """
        Load the latest text for a chapter for a given kind ("draft" or "final").

        - First tries versioned files like ch01_draft_v3.txt.
        - Then falls back to legacy names like ch01_draft.txt or ch01.txt.
        - Returns "" if nothing is found.
        """
        # 1) Try versioned files
        versions = self.list_chapter_versions(chapter_id, kind=kind)
        if versions:
            latest_path = versions[-1].path
            return latest_path.read_text(encoding="utf-8")

        # 2) Legacy name: ch01_draft.txt
        path = self.root / "chapters" / f"{chapter_id}_{kind}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")

        # 3) Legacy name: ch01.txt
        path2 = self.root / "chapters" / f"{chapter_id}.txt"
        if path2.exists():
            return path2.read_text(encoding="utf-8")

        return ""

    def save_chapter_text(self, chapter_id: str, kind: str, text: str) -> Path:
        """
        Save a new version of the chapter text.

        - Uses filenames like ch01_draft_v1.txt, ch01_final_v2.txt.
        - If the new text is identical to the latest version, does nothing
          and returns the existing path.
        - Also maintains a legacy alias filename ch01_{kind}.txt for convenience.
        """
        chapters_dir = self.root / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        kind = kind.lower()
        if kind not in ("draft", "final"):
            raise ValueError(f"Unsupported chapter kind: {kind}")

        versions = self.list_chapter_versions(chapter_id, kind=kind)
        if versions:
            latest = versions[-1]
            existing = latest.path.read_text(encoding="utf-8")
            if existing == text:
                # no change
                return latest.path
            new_version = latest.version + 1
        else:
            new_version = 1

        new_path = chapters_dir / f"{chapter_id}_{kind}_v{new_version}.txt"
        new_path.write_text(text, encoding="utf-8")

        # Legacy alias: overwrite ch01_draft.txt / ch01_final.txt
        alias_path = chapters_dir / f"{chapter_id}_{kind}.txt"
        alias_path.write_text(text, encoding="utf-8")

        return new_path

    def get_latest_text_info(self, chapter_id: str) -> tuple[str, int, str]:
        """
        Return (kind, version, text) for the latest text version of this chapter.

        Prefers "final"; falls back to "draft". If no versioned files are found,
        falls back to non-versioned load_chapter_text and treats it as
        ("draft", 1, text).
        """
        final_versions = self.list_chapter_versions(chapter_id, kind="final")
        draft_versions = self.list_chapter_versions(chapter_id, kind="draft")

        if final_versions:
            vinfo = max(final_versions, key=lambda v: v.version)
        elif draft_versions:
            vinfo = max(draft_versions, key=lambda v: v.version)
        else:
            text = (
                self.load_chapter_text(chapter_id, kind="final")
                or self.load_chapter_text(chapter_id, kind="draft")
            )
            if not text:
                raise ValueError(f"No text found for chapter {chapter_id}")
            return "draft", 1, text

        text = vinfo.path.read_text(encoding="utf-8")
        return vinfo.kind, vinfo.version, text

    # ------------------------------------------------------------------
    # Chapter summaries
    # ------------------------------------------------------------------

    def load_chapter_summary(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        """
        Load saved summary JSON for a chapter, or None if it doesn't exist.
        """
        return self._load_json(f"summaries/{chapter_id}_summary.json", default=None)

    def save_chapter_summary(self, chapter_id: str, data: Dict[str, Any]) -> None:
        """
        Save summary JSON for a chapter.
        """
        self._save_json(f"summaries/{chapter_id}_summary.json", data)

    # ------------------------------------------------------------------
    # Bible (stored as plain dict)
    # ------------------------------------------------------------------
    def load_bible(self) -> Dict[str, Any]:
        """Load the bible JSON (bible/bible.json).

        Returns a dict with keys:
          "characters", "locations", "items"
        If no file exists, returns an empty dict with those keys.
        """
        data = self._load_json("bible/bible.json", default=None)
        if data is None or not isinstance(data, dict):
            data = {}

        data.setdefault("characters", {})
        data.setdefault("locations", {})
        data.setdefault("items", {})

        return data

    def save_bible(self, bible: Any) -> None:
        """
        Save the bible JSON to bible/bible.json.

        Accepts either:
          - a dict with keys "characters", "locations", "items", or
          - any object that can be converted via asdict()/dict().
        """
        if isinstance(bible, dict):
            data = bible
        else:
            # Try dataclass
            try:
                data = asdict(bible)
            except Exception:
                # Try pydantic-style dict()
                if hasattr(bible, "model_dump"):
                    data = bible.model_dump()
                elif hasattr(bible, "dict"):
                    data = bible.dict()
                else:
                    raise TypeError("Unsupported bible object type")

        # Ensure basic structure
        if not isinstance(data, dict):
            raise TypeError("Bible must serialise to a dict")

        data.setdefault("characters", {})
        data.setdefault("locations", {})
        data.setdefault("items", {})

        bible_dir = self.root / "bible"
        bible_dir.mkdir(parents=True, exist_ok=True)
        canonical = bible_dir / "bible.json"

        new_text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)

        latest_version = 0
        if canonical.exists():
            try:
                existing_text = canonical.read_text(encoding="utf-8")
            except Exception:
                existing_text = ""
            if existing_text == new_text:
                # nothing changed; don't create new version
                return

            # find highest bible_vN.json
            pattern = re.compile(r"^bible_v(\d+)\.json$", re.IGNORECASE)
            for p in bible_dir.iterdir():
                if not p.is_file():
                    continue
                m = pattern.match(p.name)
                if not m:
                    continue
                try:
                    v = int(m.group(1))
                except ValueError:
                    continue
                if v > latest_version:
                    latest_version = v

        next_v = latest_version + 1
        version_path = bible_dir / f"bible_v{next_v}.json"
        version_path.write_text(new_text, encoding="utf-8")
        canonical.write_text(new_text, encoding="utf-8")

    # ------------------------------------------------------------------
    # Timeline (simple, can be expanded later)
    # ------------------------------------------------------------------

    def load_timeline(self) -> Dict[str, Any]:
        """
        Load the timeline JSON (timeline.json).
        Returns a dict; creates an empty structure if missing.
        """
        data = self._load_json("timeline.json", default=None)
        if data is None or not isinstance(data, dict):
            data = {"events": []}
        return data

    def save_timeline(self, data: Dict[str, Any]) -> None:
        """
        Save the timeline JSON.
        """
        self._save_json("timeline.json", data)
