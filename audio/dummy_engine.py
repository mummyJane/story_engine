# story_engine/audio/dummy_engine.py

from pathlib import Path
from .tts import TTSEngineBase


class DummyTTSEngine(TTSEngineBase):
    """
    Placeholder TTS engine.

    Instead of generating real audio, it just writes the text into a .txt file
    next to where the MP3 would go. This keeps the pipeline working until
    you plug in a real TTS backend.
    """

    def speak_to_mp3(self, text: str, out_path: Path) -> None:
        # e.g. audio/ch02.mp3 -> audio/ch02.txt
        txt_path = out_path.with_suffix(".txt")
        txt_path.write_text(text, encoding="utf-8")
