# story_engine/audio/piper_engine.py
import subprocess
from pathlib import Path
from .tts import TTSEngineBase


class PiperEngine(TTSEngineBase):
    def __init__(self, voice_model: str, piper_exe: str = "piper"):
        self.voice_model = voice_model
        self.piper_exe = piper_exe

    def speak_to_mp3(self, text: str, out_path: Path) -> None:
        wav_path = out_path.with_suffix(".wav")
        proc = subprocess.Popen(
            [
                self.piper_exe,
                "--model", self.voice_model,
                "--output_file", str(wav_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.communicate(input=text.encode("utf-8"))
        proc.wait()
        # convert or rename to mp3 depending on how you want to handle it
        wav_path.rename(out_path)
