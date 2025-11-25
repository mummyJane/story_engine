# story_engine/io/versioning.py

from __future__ import annotations

from pathlib import Path
import json
from typing import Dict, Optional


class VersionManager:
    """
    Tracks version numbers for logical files in a project.

    Stored in project_root/versions.json as:
        { "chapters/ch02_draft": 3, "bible/characters": 5, ... }
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.path = project_root / "versions.json"
        self._versions: Dict[str, int] = {}
        if self.path.exists():
            self._versions = json.loads(self.path.read_text(encoding="utf-8"))

    def get_current(self, key: str) -> Optional[int]:
        """Return current version number for this logical key, or None."""
        return self._versions.get(key)

    def next_version(self, key: str) -> int:
        """
        Increment and return the next version number for this key.
        Also persists versions.json.
        """
        current = self._versions.get(key, 0)
        new_v = current + 1
        self._versions[key] = new_v
        self._save()
        return new_v

    def set_current(self, key: str, version: int) -> None:
        """
        Force current version for a key (for manual rollbacks).
        """
        self._versions[key] = int(version)
        self._save()

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._versions, indent=2),
            encoding="utf-8",
        )
