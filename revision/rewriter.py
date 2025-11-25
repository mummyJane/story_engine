# revision/rewriter.py
from story_engine.io.project_repo import ProjectRepo
from story_engine.llm.client import LLMClient

class Rewriter:
    def __init__(self, repo: ProjectRepo, llm: LLMClient):
        self.repo = repo
        self.llm = llm

    def rewrite_chapter(self, chapter_id: str, notes: str) -> str:
        draft = self.repo.load_chapter_text(chapter_id, kind="final") \
                or self.repo.load_chapter_text(chapter_id, kind="draft_v1")

        prompt = f"""You are revising a novel chapter.

CURRENT DRAFT:
{draft}

REVISION NOTES FROM THE AUTHOR:
{notes}

TASK:
Rewrite the entire chapter from start to finish, applying the notes.
Keep plot events consistent unless the notes say otherwise.
"""

        new_text = self.llm.complete(prompt, max_tokens=4096)
        self.repo.save_chapter_text(chapter_id, new_text, kind="final")
        return new_text
