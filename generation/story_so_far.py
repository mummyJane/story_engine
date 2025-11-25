# generation/story_so_far.py
from typing import List
from story_engine.io.project_repo import ProjectRepo
from story_engine.io.schemas import ProjectConfig, ChapterSummary
import json
from pathlib import Path


def load_chapter_summary(repo: ProjectRepo, chapter_id: str) -> ChapterSummary | None:
    path = repo.chapters_dir / f"{chapter_id}_summary.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return ChapterSummary(
        chapter_id=chapter_id,
        bullet_summary=data["bullet_summary"],
        character_updates=data["character_updates"],
        location_updates=data["location_updates"],
        item_updates=data["item_updates"],
    )


def story_summaries_up_to(
    repo: ProjectRepo, cfg: ProjectConfig, chapter_id: str, max_chapters: int = 5
) -> List[ChapterSummary]:
    """Return summaries for the N chapters immediately before chapter_id in reading order."""
    order = cfg.chapter_order
    idx = order.index(chapter_id)
    start = max(0, idx - max_chapters)
    result: List[ChapterSummary] = []
    for cid in order[start:idx]:
        s = load_chapter_summary(repo, cid)
        if s:
            result.append(s)
    return result
