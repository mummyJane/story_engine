# story_engine/web/app.py

from pathlib import Path
from datetime import datetime
import re
import json
import difflib

from fastapi import FastAPI, Request, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from story_engine.io.project_repo import ProjectRepo
from story_engine.io.schemas import ChapterOutline, CharacterRecord, CharacterState, LocationRecord, ItemRecord
from story_engine.llm.client import LLMClient
from story_engine.generation.chapter_generator import ChapterGenerator
from story_engine.generation.summariser import Summariser
from story_engine.audio.tts import StoryTTS
from story_engine.audio.piper_engine import PiperEngine
from story_engine.io.exporting import export_txt, export_md, export_docx, export_campfire


# Root that contains the "stories" folder.
# Adjust this if your layout is different.
ROOT = Path(__file__).resolve().parents[2]
STORIES_ROOT = ROOT / "stories"
LMSTUDIO_BASE_URL = "http://127.0.0.1:1234"  # adjust if your port is different
DEFAULT_LMSTUDIO_MODEL = "qwen2.5-14b-instruct-1m"  # set to something that exists in LM Studio


def get_llm(model_name: str | None) -> LLMClient:
    return LLMClient(
        base_url=LMSTUDIO_BASE_URL,
        model_name=model_name or DEFAULT_LMSTUDIO_MODEL,
    )


def get_project_root(project_name: str) -> Path:
    root = STORIES_ROOT / project_name
    if not (root / "project.json").exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
    return root


def get_services(project_name: str):
    project_root = get_project_root(project_name)
    repo = ProjectRepo(project_root)
    cfg = repo.load_project_config()
    model_name = getattr(cfg, "model_name", None)
    llm = get_llm(model_name)
    gen = ChapterGenerator(repo, llm)
    summ = Summariser(repo, llm)
    tts = StoryTTS(
        repo,
        PiperEngine(
            voice_model=ROOT / "piper" / "en_GB-cori-high.onnx",
            piper_exe="piper",
        ),
    )
    return repo, gen, summ, tts, project_root


app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# --- Add Jinja filter for formatting timestamps ---
def format_datetime(value: float) -> str:
    try:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


templates.env.filters["datetime"] = format_datetime


# ---------------------------------------------------------------------------
# Story selection
# ---------------------------------------------------------------------------

@app.get("/")
def list_projects(request: Request):
    STORIES_ROOT.mkdir(parents=True, exist_ok=True)
    projects = [
        sub.name
        for sub in STORIES_ROOT.iterdir()
        if (sub / "project.json").exists()
    ]
    return templates.TemplateResponse(
        "projects.html",
        {"request": request, "projects": projects},
    )


# ---------------------------------------------------------------------------
# Project view
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/project")
def project_view(request: Request, project_name: str):
    repo, _, _, _, _ = get_services(project_name)
    cfg = repo.load_project_config()
    return templates.TemplateResponse(
        "project.html",
        {"request": request, "cfg": cfg, "project_name": project_name},
    )


# ---------------------------------------------------------------------------
# Bible view
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/bible")
def bible_view(request: Request, project_name: str):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()  # dict with keys: characters, locations, items
    return templates.TemplateResponse(
        "bible.html",
        {"request": request, "bible": bible, "project_name": project_name},
    )


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/bible/characters")
def characters_list(request: Request, project_name: str):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()
    return templates.TemplateResponse(
        "characters.html",
        {"request": request, "bible": bible, "project_name": project_name},
    )


@app.get("/projects/{project_name}/bible/characters/new")
def new_character_form(request: Request, project_name: str):
    return templates.TemplateResponse(
        "character_edit.html",
        {
            "request": request,
            "name": "",
            "record": None,
            "project_name": project_name,
        },
    )


@app.get("/projects/{project_name}/bible/characters/{name}")
def edit_character(request: Request, project_name: str, name: str):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()
    rec = bible.characters.get(name)
    return templates.TemplateResponse(
        "character_edit.html",
        {
            "request": request,
            "name": name,
            "record": rec,
            "project_name": project_name,
        },
    )


@app.post("/projects/{project_name}/bible/characters/save")
async def save_character(
    project_name: str,
    name: str = Form(...),
    bio: str = Form(""),
    tags: str = Form(""),
    location: str = Form(""),
):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()

    tags_list = [
        t.strip()
        for t in re.split(r"[,\n]", tags)
        if t.strip()
    ]
    loc = location.strip() or None

    if name in bible.characters:
        rec = bible.characters[name]
        rec.bio = bio
        rec.tags = tags_list
        rec.current_state.location = loc
    else:
        cs = CharacterState(location=loc)
        rec = CharacterRecord(name=name, bio=bio, tags=tags_list, current_state=cs)
        bible.characters[name] = rec

    repo.save_bible(bible)
    return RedirectResponse(
        url=f"/projects/{project_name}/bible", status_code=303
    )


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/bible/locations")
def locations_list(request: Request, project_name: str):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()
    return templates.TemplateResponse(
        "locations.html",
        {"request": request, "bible": bible, "project_name": project_name},
    )


@app.get("/projects/{project_name}/bible/locations/new")
def new_location_form(request: Request, project_name: str):
    return templates.TemplateResponse(
        "location_edit.html",
        {
            "request": request,
            "name": "",
            "record": None,
            "project_name": project_name,
        },
    )


@app.get("/projects/{project_name}/bible/locations/{name}")
def edit_location(request: Request, project_name: str, name: str):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()
    rec = bible.locations.get(name)
    return templates.TemplateResponse(
        "location_edit.html",
        {
            "request": request,
            "name": name,
            "record": rec,
            "project_name": project_name,
        },
    )


@app.post("/projects/{project_name}/bible/locations/save")
async def save_location(
    project_name: str,
    name: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()

    tags_list = [
        t.strip()
        for t in re.split(r"[,\n]", tags)
        if t.strip()
    ]

    if name in bible.locations:
        loc = bible.locations[name]
        loc.description = description
        loc.tags = tags_list
    else:
        loc = LocationRecord(
            name=name,
            description=description,
            tags=tags_list,
            notes=[],
        )
        bible.locations[name] = loc

    repo.save_bible(bible)
    return RedirectResponse(
        url=f"/projects/{project_name}/bible", status_code=303
    )


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/bible/items")
def items_list(request: Request, project_name: str):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()
    return templates.TemplateResponse(
        "items.html",
        {"request": request, "bible": bible, "project_name": project_name},
    )


@app.get("/projects/{project_name}/bible/items/new")
def new_item_form(request: Request, project_name: str):
    return templates.TemplateResponse(
        "item_edit.html",
        {
            "request": request,
            "name": "",
            "record": None,
            "project_name": project_name,
        },
    )


@app.get("/projects/{project_name}/bible/items/{name}")
def edit_item(request: Request, project_name: str, name: str):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()
    rec = bible.items.get(name)
    return templates.TemplateResponse(
        "item_edit.html",
        {
            "request": request,
            "name": name,
            "record": rec,
            "project_name": project_name,
        },
    )


@app.post("/projects/{project_name}/bible/items/save")
async def save_item(
    project_name: str,
    name: str = Form(...),
    description: str = Form(""),
    owner: str = Form(""),
    location: str = Form(""),
    state: str = Form("intact"),
    tags: str = Form(""),
):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()

    tags_list = [
        t.strip()
        for t in re.split(r"[,\n]", tags)
        if t.strip()
    ]
    owner_val = owner.strip() or None
    loc_val = location.strip() or None

    if name in bible.items:
        it = bible.items[name]
        it.description = description
        it.owner = owner_val
        it.location = loc_val
        it.state = state or "intact"
        it.tags = tags_list
    else:
        it = ItemRecord(
            name=name,
            description=description,
            owner=owner_val,
            location=loc_val,
            state=state or "intact",
            tags=tags_list,
        )
        bible.items[name] = it

    repo.save_bible(bible)
    return RedirectResponse(
        url=f"/projects/{project_name}/bible", status_code=303
    )


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/timeline")
def timeline_view(request: Request, project_name: str):
    repo, _, _, _, _ = get_services(project_name)
    bible = repo.load_bible()
    return templates.TemplateResponse(
        "timeline.html",
        {"request": request, "timeline": bible.timeline, "project_name": project_name},
    )

@app.post("/projects/{project_name}/timeline/rebuild")
async def rebuild_timeline(project_name: str):
    _, _, summ, _, _ = get_services(project_name)
    summ.rebuild_timeline()
    return RedirectResponse(
        url=f"/projects/{project_name}/timeline", status_code=303
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/export/{fmt}")
def export_project(project_name: str, fmt: str):
    """
    Export the story in one of: txt, md, docx, campfire.

    Returns a file download.
    """
    repo, _, _, _, project_root = get_services(project_name)
    fmt = fmt.lower()
    if fmt not in {"txt", "md", "docx", "campfire"}:
        raise HTTPException(status_code=400, detail="fmt must be one of: txt, md, docx, campfire")

    exports_dir = project_root / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    # simple filename based on project name
    if fmt == "txt":
        out_path = exports_dir / f"{project_name}.txt"
        export_txt(repo, out_path)
        media_type = "text/plain"
    elif fmt == "md":
        out_path = exports_dir / f"{project_name}.md"
        export_md(repo, out_path)
        media_type = "text/markdown"
    elif fmt == "docx":
        out_path = exports_dir / f"{project_name}.docx"
        export_docx(repo, out_path)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:  # campfire
        out_path = exports_dir / f"{project_name}_campfire.json"
        export_campfire(repo, out_path)
        media_type = "application/json"

    return FileResponse(
        path=str(out_path),
        media_type=media_type,
        filename=out_path.name,
    )


# ---------------------------------------------------------------------------
# Chapter view / edit / actions
# ---------------------------------------------------------------------------

# 1) NEW CHAPTER FORM – must come first
@app.get("/projects/{project_name}/chapters/new")
def new_chapter_form(request: Request, project_name: str):
    repo, _, _, _, _ = get_services(project_name)
    cfg = repo.load_project_config()

    # Suggest next id: ch01, ch02, ...
    suggested_id = "ch01"
    if cfg.chapter_order:
        import re as _re
        max_n = 0
        for cid in cfg.chapter_order:
            m = _re.search(r"(\d+)$", cid)
            if m:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
        if max_n > 0:
            suggested_id = f"ch{max_n + 1:02d}"

    return templates.TemplateResponse(
        "chapter_new.html",
        {
            "request": request,
            "project_name": project_name,
            "cfg": cfg,
            "suggested_id": suggested_id,
        },
    )


# 2) CREATE CHAPTER HANDLER
@app.post("/projects/{project_name}/chapters/create")
async def create_chapter(
    project_name: str,
    chapter_id: str = Form(...),
    title: str = Form(""),
    pov: str = Form(""),
    target_word_count: int = Form(1800),
):
    repo, _, _, _, _ = get_services(project_name)

    chapter_id = chapter_id.strip()
    if not chapter_id:
        raise HTTPException(status_code=400, detail="chapter_id is required")

    cfg = repo.load_project_config()

    # If it already exists, just go to it
    if chapter_id in cfg.chapter_order:
        return RedirectResponse(
            url=f"/projects/{project_name}/chapters/{chapter_id}",
            status_code=303,
        )

    # Append to chapter_order and save project.json
    cfg.chapter_order.append(chapter_id)
    repo.save_project_config(cfg)

    # Create minimal outline
    outline = {
        "chapter_id": chapter_id,
        "title": title.strip() or chapter_id,
        "pov": pov.strip(),
        "target_word_count": int(target_word_count),
        "beats": [],
        "must_include": [],
        "avoid": [],
    }
    repo.save_chapter_outline(chapter_id, outline)

    return RedirectResponse(
        url=f"/projects/{project_name}/chapters/{chapter_id}",
        status_code=303,
    )


# 3) GENERIC CHAPTER VIEW – must come AFTER the `/new` route
@app.get("/projects/{project_name}/chapters/{chapter_id}")
def chapter_view(request: Request, project_name: str, chapter_id: str):
    repo, _, _, _, _ = get_services(project_name)
    cfg = repo.load_project_config()
    outline_dict = repo.load_chapter_outline(chapter_id)
    outline = ChapterOutline(**outline_dict) if outline_dict else None
    final = repo.load_chapter_text(chapter_id, kind="final")
    draft = repo.load_chapter_text(chapter_id, kind="draft")
    text = final or draft or ""
    return templates.TemplateResponse(
        "chapter.html",
        {
            "request": request,
            "cfg": cfg,
            "project_name": project_name,
            "chapter_id": chapter_id,
            "outline": outline,
            "text": text,
        },
    )


@app.post("/projects/{project_name}/chapters/{chapter_id}/outline")
async def save_outline(
    project_name: str,
    chapter_id: str,
    title: str = Form(...),
    pov: str = Form(...),
    target_word_count: int = Form(...),
    beats: str = Form(""),
    must_include: str = Form(""),
    avoid: str = Form(""),
):
    repo, _, _, _, _ = get_services(project_name)
    outline = {
        "chapter_id": chapter_id,
        "title": title,
        "pov": pov,
        "target_word_count": int(target_word_count),
        "beats": [b.strip() for b in beats.splitlines() if b.strip()],
        "must_include": [m.strip() for m in must_include.splitlines() if m.strip()],
        "avoid": [a.strip() for a in avoid.splitlines() if a.strip()],
    }
    repo.save_chapter_outline(chapter_id, outline)
    return RedirectResponse(
        url=f"/projects/{project_name}/chapters/{chapter_id}", status_code=303
    )


@app.post("/projects/{project_name}/chapters/{chapter_id}/generate")
async def generate(project_name: str, chapter_id: str):
    _, gen, _, _, _ = get_services(project_name)
    gen.generate_chapter(chapter_id)
    return RedirectResponse(
        url=f"/projects/{project_name}/chapters/{chapter_id}", status_code=303
    )


@app.post("/projects/{project_name}/chapters/{chapter_id}/summarise")
async def summarise_chapter(project_name: str, chapter_id: str):
    repo, _, summ, _, _ = get_services(project_name)
    # make sure there is text
    text = (
        repo.load_chapter_text(chapter_id, kind="final")
        or repo.load_chapter_text(chapter_id, kind="draft")
    )
    if not text:
        raise HTTPException(status_code=400, detail="No text to summarise")

    # Summarise without mutating the bible directly
    summ.summarise_chapter(chapter_id, apply_to_bible=False)

    # Rebuild bible state up to this chapter and refresh the timeline
    summ.rebuild_state_from(chapter_id)
    summ.rebuild_timeline()

    return RedirectResponse(
        url=f"/projects/{project_name}/chapters/{chapter_id}", status_code=303
    )


@app.post("/projects/{project_name}/chapters/{chapter_id}/rebuild_state")
async def rebuild_state_from(project_name: str, chapter_id: str):
    _, _, summ, _, _ = get_services(project_name)
    summ.rebuild_state_from(chapter_id)
    return RedirectResponse(
        url=f"/projects/{project_name}/chapters/{chapter_id}", status_code=303
    )


@app.post("/projects/{project_name}/chapters/{chapter_id}/audio")
async def chapter_audio(project_name: str, chapter_id: str):
    _, _, _, tts, project_root = get_services(project_name)
    out_dir = project_root / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    tts.chapter_to_mp3(chapter_id, out_dir)
    return RedirectResponse(
        url=f"/projects/{project_name}/chapters/{chapter_id}", status_code=303
    )


@app.post("/projects/{project_name}/chapters/{chapter_id}/run_pipeline")
async def run_pipeline(project_name: str, chapter_id: str):
    repo, gen, summ, _, _ = get_services(project_name)

    # Determine previous chapter in the configured order (if any)
    cfg = repo.load_project_config()
    order = getattr(cfg, "chapter_order", None) or []
    prev_id = None
    if chapter_id in order:
        idx = order.index(chapter_id)
        if idx > 0:
            prev_id = order[idx - 1]

    # Rebuild bible to the state just BEFORE this chapter,
    # so generation sees only prior events, not future ones.
    if prev_id:
        summ.rebuild_state_from(prev_id)
    else:
        # No previous chapter: reset to an empty baseline bible
        repo.save_bible({"characters": {}, "locations": {}, "items": {}})

    # Only generate if there isn't already a final version
    final = repo.load_chapter_text(chapter_id, kind="final")
    if not final:
        gen.generate_chapter(chapter_id)

    # Summarise without directly mutating the bible
    summ.summarise_chapter(chapter_id, apply_to_bible=False)

    # Rebuild bible state including this chapter and refresh the timeline
    summ.rebuild_state_from(chapter_id)
    summ.rebuild_timeline()

    return RedirectResponse(
        url=f"/projects/{project_name}/chapters/{chapter_id}", status_code=303
    )


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/model")
def model_select_view(request: Request, project_name: str):
    repo, _, _, _, _ = get_services(project_name)
    cfg = repo.load_project_config()

    # Create a temporary client just to talk to LM Studio
    client = LLMClient(base_url=LMSTUDIO_BASE_URL, model_name=cfg.model_name or DEFAULT_LMSTUDIO_MODEL)

    error = None
    models = []
    try:
        models = client.list_models()
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(
        "model_select.html",
        {
            "request": request,
            "project_name": project_name,
            "cfg": cfg,
            "models": models,
            "error": error,
        },
    )


@app.post("/projects/{project_name}/model/select")
async def model_select_post(
    project_name: str,
    model_id: str = Form(...),
):
    repo, _, _, _, _ = get_services(project_name)
    cfg = repo.load_project_config()

    # Set the model_name on the config
    if hasattr(cfg, "model_name"):
        cfg.model_name = model_id
    else:
        # very unlikely if you added it to ProjectConfig, but just in case
        raise HTTPException(status_code=500, detail="ProjectConfig has no model_name field")

    repo.save_project_config(cfg)
    return RedirectResponse(
        url=f"/projects/{project_name}/project",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# New project
# ---------------------------------------------------------------------------

@app.get("/projects/new")
def new_project_form(request: Request):
    """
    Simple form to create a new story under STORIES_ROOT.
    """
    return templates.TemplateResponse(
        "project_new.html",
        {"request": request},
    )


@app.post("/projects/create")
async def create_project(
    folder_name: str = Form(...),
    title: str = Form(...),
    author: str = Form(""),
    tone: str = Form(""),
):
    folder = folder_name.strip()
    if not folder:
        raise HTTPException(status_code=400, detail="folder_name is required")

    root = STORIES_ROOT / folder
    if root.exists():
        raise HTTPException(status_code=400, detail="Project folder already exists")

    # Create basic layout
    root.mkdir(parents=True)
    (root / "chapters").mkdir()
    (root / "bible").mkdir()

    cfg = {
        "title": title.strip() or folder,
        "author": author.strip() or "",
        "chapter_order": [],
        "style_rules": [],
        "tone": tone.strip() or "",
        "model_name": None,
    }

    with (root / "project.json").open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    return RedirectResponse(
        url=f"/projects/{folder}/project",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/notes")
def notes_view(request: Request, project_name: str):
    """
    View/edit freeform notes for this story.
    Stored as notes.md in the project root.
    """
    _, _, _, _, project_root = get_services(project_name)
    notes_path = project_root / "notes.md"
    text = ""
    if notes_path.exists():
        text = notes_path.read_text(encoding="utf-8")
    return templates.TemplateResponse(
        "notes.html",
        {"request": request, "project_name": project_name, "text": text},
    )


@app.post("/projects/{project_name}/notes")
async def notes_save(
    project_name: str,
    text: str = Form(""),
):
    _, _, _, _, project_root = get_services(project_name)
    notes_path = project_root / "notes.md"
    notes_path.write_text(text, encoding="utf-8")
    return RedirectResponse(
        url=f"/projects/{project_name}/notes", status_code=303
    )


# ---------------------------------------------------------------------------
# Chapter summary + versions + diff
# ---------------------------------------------------------------------------

@app.get("/projects/{project_name}/chapters/{chapter_id}/summary")
def chapter_summary_view(request: Request, project_name: str, chapter_id: str):
    repo, _, _, _, _ = get_services(project_name)
    summary = repo.load_chapter_summary(chapter_id)
    return templates.TemplateResponse(
        "chapter_summary.html",
        {
            "request": request,
            "project_name": project_name,
            "chapter_id": chapter_id,
            "summary": summary,
        },
    )


@app.get("/projects/{project_name}/chapters/{chapter_id}/versions")
def chapter_versions_view(request: Request, project_name: str, chapter_id: str):
    repo, _, _, _, _ = get_services(project_name)
    draft_versions = repo.list_chapter_versions(chapter_id, kind="draft")
    final_versions = repo.list_chapter_versions(chapter_id, kind="final")
    return templates.TemplateResponse(
        "chapter_versions.html",
        {
            "request": request,
            "project_name": project_name,
            "chapter_id": chapter_id,
            "draft_versions": draft_versions,
            "final_versions": final_versions,
        },
    )


@app.get("/projects/{project_name}/chapters/{chapter_id}/diff")
def chapter_diff_view(
    request: Request,
    project_name: str,
    chapter_id: str,
    kind: str = Query("draft"),
    v1: int = Query(...),
    v2: int = Query(...),
):
    repo, _, _, _, _ = get_services(project_name)
    text1 = repo.load_chapter_text_version(chapter_id, kind, v1)
    text2 = repo.load_chapter_text_version(chapter_id, kind, v2)

    diff_html = difflib.HtmlDiff().make_table(
        text1.splitlines(),
        text2.splitlines(),
        f"{chapter_id} {kind} v{v1}",
        f"{chapter_id} {kind} v{v2}",
        context=True,
        numlines=3,
    )

    return templates.TemplateResponse(
        "chapter_diff.html",
        {
            "request": request,
            "project_name": project_name,
            "chapter_id": chapter_id,
            "kind": kind,
            "v1": v1,
            "v2": v2,
            "diff_html": diff_html,
        },
    )
