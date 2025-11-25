# audio/tts.py
from pathlib import Path
from story_engine.io.project_repo import ProjectRepo
from story_engine.io.schemas import Bible


class TTSEngineBase:
    """Abstract TTS engine interface."""
    def speak_to_mp3(self, text: str, out_path: Path) -> None:
        raise NotImplementedError


class StoryTTS:
    def __init__(self, repo: ProjectRepo, engine: TTSEngineBase):
        self.repo = repo
        self.engine = engine

    def chapter_to_mp3(self, chapter_id: str, out_dir: Path) -> Path:
        """
        Generate an MP3 for the latest version of this chapter.

        - Uses ProjectRepo.get_latest_text_info() to find (kind, version, text).
        - Names file like ch01_draft_v5.mp3.
        - If that filename already exists, appends _2, _3, etc.
        """
        kind, version, text = self.repo.get_latest_text_info(chapter_id)

        out_dir.mkdir(parents=True, exist_ok=True)

        base_name = f"{chapter_id}_{kind}_v{version}.mp3"
        mp3_path = out_dir / base_name

        # If file already exists, append a numeric suffix
        if mp3_path.exists():
            idx = 2
            while True:
                alt = out_dir / f"{chapter_id}_{kind}_v{version}_{idx}.mp3"
                if not alt.exists():
                    mp3_path = alt
                    break
                idx += 1

        self.engine.speak_to_mp3(text, mp3_path)
        return mp3_path

    def bible_to_mp3(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        bible: Bible = self.repo.load_bible()

        parts = []

        parts.append("CHARACTERS:")
        for c in bible.characters.values():
            parts.append(f"{c.name}. {c.bio}")
            if c.current_state.location:
                parts.append(f"Currently at {c.current_state.location}.")

        parts.append("\nLOCATIONS:")
        for loc in bible.locations.values():
            parts.append(f"{loc.name}. {loc.description}")

        parts.append("\nITEMS:")
        for it in bible.items.values():
            owner = f" owned by {it.owner}" if it.owner else ""
            parts.append(f"{it.name}{owner}. {it.description}")

        text = "\n".join(parts)
        out_path = out_dir / "bible.mp3"
        self.engine.speak_to_mp3(text, out_path)
        return out_path
