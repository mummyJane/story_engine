# story_engine/cli/main.py

import typer
from pathlib import Path
from typing import Literal
from datetime import datetime

from story_engine.io.project_repo import ProjectRepo, VersionInfo
from story_engine.io.project_repo import ProjectRepo
from story_engine.io.schemas import ProjectConfig, Bible
from story_engine.io.schemas import CharacterRecord, CharacterState, LocationRecord, ItemRecord
from story_engine.io.versioning import VersionManager
from story_engine.llm.client import LLMClient
from story_engine.generation.chapter_generator import ChapterGenerator
from story_engine.generation.summariser import Summariser
from story_engine.revision.rewriter import Rewriter
from story_engine.audio.tts import StoryTTS
from story_engine.audio.piper_engine import PiperEngine
from story_engine.audio.dummy_engine import DummyTTSEngine
from story_engine.io.exporting import export_txt, export_md, export_docx, export_campfire

app = typer.Typer()

def get_repo(project_root: Path) -> ProjectRepo:
    return ProjectRepo(project_root)

def get_llm() -> LLMClient:
    # adapt base_url/model_name to your local setup
    return LLMClient(base_url="http://localhost:1234", model_name="qwen2.5-14b-instruct-1m")

@app.command()
def generate_chapter(
    chapter_id: str,
    project_root: Path = typer.Option(Path("."), help="Path to the story project root"),
):
    repo = get_repo(project_root)
    llm = get_llm()
    gen = ChapterGenerator(repo, llm)
    text = gen.generate_chapter(chapter_id)
    typer.echo(f"Generated draft for {chapter_id} ({len(text)} chars).")


@app.command()
def rewrite_chapter(
    chapter_id: str = typer.Argument(..., help="Chapter ID, e.g. ch02"),
    notes_file: Path = typer.Option(..., "--notes-file", "-n", help="Path to notes text file"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-p", help="Story project root"),
):
    repo = get_repo(project_root)
    llm = get_llm()
    notes = notes_file.read_text(encoding="utf-8")
    rw = Rewriter(repo, llm)
    new_text = rw.rewrite_chapter(chapter_id, notes)
    typer.echo(f"Rewrote {chapter_id} ({len(new_text)} chars).")


@app.command(name="rebuild-state")
def rebuild_state_cmd(
    from_chapter: str = typer.Option(..., "--from-chapter"),
    project_root: Path = typer.Option(Path("."), help="Path to the story project root"),
):
    repo = get_repo(project_root)
    llm = get_llm()
    s = Summariser(repo, llm)
    s.rebuild_state_from(from_chapter)
    typer.echo(f"Rebuilt state from {from_chapter} onward.")


@app.command()
def chapter_to_mp3(
    chapter_id: str,
    project_root: Path = typer.Option(Path("."), help="Path to the story project root"),
    out_dir: Path = typer.Option(Path("audio"), help="Output directory for MP3s"),
):
    repo = get_repo(project_root)
    tts = StoryTTS(repo, PiperEngine(voice_model="en_GB-cori-high.onnx"))
#    tts = StoryTTS(repo, DummyTTSEngine())
    out_path = tts.chapter_to_mp3(chapter_id, out_dir)
    typer.echo(f"Wrote {out_path}")
#    typer.echo(f"Wrote {out_path.with_suffix('.txt')} (dummy TTS text output)")

@app.command()
def bible_to_mp3(
    project_root: Path = typer.Option(Path("."), help="Path to the story project root"),
    out_dir: Path = typer.Option(Path("audio"), help="Output directory for MP3s"),
):
    repo = get_repo(project_root)
    tts = StoryTTS(repo, PiperEngine(voice_model="your-voice-model.onnx"))
#    tts = StoryTTS(repo, DummyTTSEngine())
    out_path = tts.bible_to_mp3(out_dir)
    typer.echo(f"Wrote {out_path}")
#    typer.echo(f"Wrote {out_path.with_suffix('.txt')} (dummy TTS text output)")

@app.command("set-version")
def set_version(
    key: str = typer.Argument(..., help="Logical key, e.g. chapters/ch02_final"),
    version: int = typer.Argument(..., help="Version number to set as current, e.g. 1"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-p"),
):
    """
    Force the current version for a given logical file key.
    Does not delete files; just updates versions.json.
    """
    vm = VersionManager(project_root)

    # Optional: sanity check the file exists
    rel_dir, base_name = key.split("/", 1)
    root = project_root / rel_dir
    pattern = f"{base_name}_v{version}.*"
    matches = list(root.glob(pattern))

    if not matches:
        typer.echo(f"Warning: no files matching {pattern} under {root}")
        # You can abort here if you want:
        # raise typer.Exit(code=1)

    vm.set_current(key, version)
    typer.echo(f"Set {key} to current v{version}")

@app.command("list-versions")
def list_versions(
    project_root: Path = typer.Option(Path("."), "--project-root", "-p", help="Story project root"),
):
    """
    Show all tracked version keys and their current version numbers.
    """
    vm = VersionManager(project_root)
    data = vm._versions  # it's just a dict {key: version}

    if not data:
        typer.echo("No versions recorded yet.")
        raise typer.Exit()

    # Pretty-print
    typer.echo("Tracked file versions:")
    for key, v in sorted(data.items()):
        typer.echo(f"  {key}: current v{v}")

@app.command("init-project")
def init_project(
    project_root: Path = typer.Argument(..., help="Directory for the new story project"),
    title: str = typer.Option("Untitled Story", "--title", "-t"),
    author: str = typer.Option("Unknown", "--author", "-a"),
    tone: str = typer.Option("dark, realistic, slow-burn", "--tone"),
):
    """
    Initialise a new story project folder with project.json, bible, and chapters dir.
    """
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "bible").mkdir(exist_ok=True)
    (project_root / "chapters").mkdir(exist_ok=True)
    (project_root / "notes").mkdir(exist_ok=True)

    repo = ProjectRepo(project_root)

    cfg = ProjectConfig(
        title=title,
        author=author,
        tone=tone,
        style_rules=[
            "Third-person limited POV unless otherwise stated.",
            "Clear, grounded descriptions; avoid purple prose.",
        ],
        chapter_order=[],
    )
    repo.save_project_config(cfg)

    # Empty bible
    bible = Bible()
    repo.save_bible(bible)

    typer.echo(f"Initialised project at {project_root}")

@app.command("create-chapter")
def create_chapter(
    chapter_id: str = typer.Argument(..., help="Chapter ID, e.g. ch01, ch02a"),
    title: str = typer.Option("Untitled Chapter", "--title", "-t"),
    pov: str = typer.Option("Daniel", "--pov", "-p", help="POV character name"),
    target_word_count: int = typer.Option(1800, "--words", "-w"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
    after: str = typer.Option(None, "--after", help="Insert after this chapter_id"),
    before: str = typer.Option(None, "--before", help="Insert before this chapter_id"),
):
    """
    Create a new chapter outline and add it to chapter_order.
    """
    if after and before:
        raise typer.BadParameter("Use only one of --after or --before, not both.")

    repo = get_repo(project_root)
    cfg = repo.load_project_config()

    if chapter_id in cfg.chapter_order:
        typer.echo(f"Chapter {chapter_id} already exists in chapter_order.")
        raise typer.Exit(code=1)

    # Decide where to insert
    if after:
        if after not in cfg.chapter_order:
            raise typer.BadParameter(f"--after: chapter_id {after} not in chapter_order")
        idx = cfg.chapter_order.index(after) + 1
        cfg.chapter_order.insert(idx, chapter_id)
    elif before:
        if before not in cfg.chapter_order:
            raise typer.BadParameter(f"--before: chapter_id {before} not in chapter_order")
        idx = cfg.chapter_order.index(before)
        cfg.chapter_order.insert(idx, chapter_id)
    else:
        cfg.chapter_order.append(chapter_id)

    repo.save_project_config(cfg)

    # Skeleton outline
    outline = {
        "chapter_id": chapter_id,
        "title": title,
        "pov": pov,
        "target_word_count": target_word_count,
        "beats": [
            "Beat 1: TODO.",
            "Beat 2: TODO.",
            "Beat 3: TODO."
        ],
        "must_include": [],
        "avoid": [],
    }

    repo.save_chapter_outline(chapter_id, outline)

    # Optional notes stub
    notes_dir = project_root / "notes"
    notes_dir.mkdir(exist_ok=True)
    notes_path = notes_dir / f"{chapter_id}_notes.txt"
    if not notes_path.exists():
        notes_path.write_text(
            "# Notes for rewrite/refinement\n\n- Add specific revision notes here.\n",
            encoding="utf-8",
        )

    typer.echo(f"Created outline for {chapter_id} and updated chapter_order.")

@app.command("list-chapters")
def list_chapters(
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    List chapters in current reading order.
    """
    repo = get_repo(project_root)
    cfg = repo.load_project_config()

    if not cfg.chapter_order:
        typer.echo("No chapters defined yet.")
        raise typer.Exit()

    typer.echo(f"Chapters for '{cfg.title}':")
    for idx, cid in enumerate(cfg.chapter_order, start=1):
        typer.echo(f"  {idx:02d}. {cid}")

@app.command("add-character")
def add_character(
    name: str = typer.Argument(..., help="Character name, e.g. Daniel"),
    bio: str = typer.Option("", "--bio", help="Short description/bio"),
    tags: list[str] = typer.Option([], "--tag", help="Tags, can repeat, e.g. --tag POV --tag main"),
    location: str = typer.Option(None, "--location", help="Starting location name"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    Add or update a character in the bible.
    """
    repo = get_repo(project_root)
    bible = repo.load_bible()

    if name in bible.characters:
        typer.echo(f"Updating existing character: {name}")
        rec = bible.characters[name]
        if bio:
            rec.bio = bio
        if tags:
            rec.tags = tags
        if location:
            rec.current_state.location = location
    else:
        typer.echo(f"Creating new character: {name}")
        cs = CharacterState(location=location)
        rec = CharacterRecord(name=name, bio=bio, tags=tags, current_state=cs)
        bible.characters[name] = rec

    repo.save_bible(bible)
    typer.echo("Bible saved (characters updated).")

@app.command("add-location")
def add_location(
    name: str = typer.Argument(..., help="Location name, e.g. Unit 1 - Babies"),
    description: str = typer.Option("", "--description", "-d"),
    tags: list[str] = typer.Option([], "--tag", help="Tags, e.g. --tag indoor --tag ward"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    Add or update a location in the bible.
    """
    repo = get_repo(project_root)
    bible = repo.load_bible()

    if name in bible.locations:
        typer.echo(f"Updating existing location: {name}")
        loc = bible.locations[name]
        if description:
            loc.description = description
        if tags:
            loc.tags = tags
    else:
        typer.echo(f"Creating new location: {name}")
        loc = LocationRecord(
            name=name,
            description=description,
            tags=tags,
            notes=[],
        )
        bible.locations[name] = loc

    repo.save_bible(bible)
    typer.echo("Bible saved (locations updated).")

@app.command("add-item")
def add_item(
    name: str = typer.Argument(..., help="Item name, e.g. Daniel's wheelchair"),
    description: str = typer.Option("", "--description", "-d"),
    owner: str = typer.Option(None, "--owner", help="Character name who owns/uses it"),
    location: str = typer.Option(None, "--location", help="Where the item is normally kept"),
    state: str = typer.Option("intact", "--state", help="new|intact|damaged|destroyed"),
    tags: list[str] = typer.Option([], "--tag", help="Tags, e.g. --tag medical --tag restraint"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    Add or update an item in the bible.
    """
    repo = get_repo(project_root)
    bible = repo.load_bible()

    if name in bible.items:
        typer.echo(f"Updating existing item: {name}")
        it = bible.items[name]
        if description:
            it.description = description
        if owner is not None:
            it.owner = owner
        if location is not None:
            it.location = location
        if state:
            it.state = state
        if tags:
            it.tags = tags
    else:
        typer.echo(f"Creating new item: {name}")
        it = ItemRecord(
            name=name,
            description=description,
            owner=owner,
            location=location,
            state=state,
            tags=tags,
        )
        bible.items[name] = it

    repo.save_bible(bible)
    typer.echo("Bible saved (items updated).")

@app.command("rebuild-timeline")
def rebuild_timeline_cmd(
    project_root: Path = typer.Option(Path("."), "--project-root", "-r", help="Story project root"),
):
    """
    Rebuild the bible timeline from chapter summaries.

    This will call the LLM to summarise chapters that don't yet have a summary.
    """
    repo = get_repo(project_root)
    llm = get_llm()
    s = Summariser(repo, llm)
    s.rebuild_timeline()
    typer.echo("Rebuilt timeline from chapter summaries.")

@app.command("list-timeline")
def list_timeline(
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    Print the current timeline events grouped by chapter.
    """
    repo = get_repo(project_root)
    bible = repo.load_bible()

    if not bible.timeline:
        typer.echo("Timeline is empty. Run 'rebuild-timeline' first.")
        raise typer.Exit()

    current_ch = None
    for ev in bible.timeline:
        if ev.chapter_id != current_ch:
            current_ch = ev.chapter_id
            typer.echo(f"\n{current_ch}:")
        typer.echo(f"  {ev.order_in_chapter:02d}. {ev.summary}")

@app.command("export-story")
def export_story(
    fmt: Literal["txt", "md", "docx", "campfire"] = typer.Argument(...),
    out: Path = typer.Argument(..., help="Output file path"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    repo = get_repo(project_root)
    if fmt == "txt":
        export_txt(repo, out)
    elif fmt == "md":
        export_md(repo, out)
    elif fmt == "docx":
        export_docx(repo, out)
    elif fmt == "campfire":
        export_campfire(repo, out)
    typer.echo(f"Exported {fmt} to {out}")

@app.command("chapter-versions")
def chapter_versions(
    chapter_id: str = typer.Argument(..., help="Chapter ID, e.g. ch02"),
    kind: str = typer.Option("final", "--kind", "-k", help="final or draft"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    List all saved versions for a chapter (draft or final) with timestamps.
    """
    repo = get_repo(project_root)
    versions = repo.list_chapter_versions(chapter_id, kind)

    if not versions:
        typer.echo(f"No versions found for {chapter_id} ({kind}).")
        raise typer.Exit()

    typer.echo(f"Versions for {chapter_id} ({kind}):")
    for v in versions:
        ts = datetime.fromtimestamp(v.mtime).strftime("%Y-%m-%d %H:%M:%S")
        typer.echo(f"  v{v.version:02d}  {ts}  {v.path.name}")

@app.command("chapter-show-version")
def chapter_show_version(
    chapter_id: str = typer.Argument(..., help="Chapter ID, e.g. ch02"),
    version: int = typer.Argument(..., help="Version number, e.g. 1"),
    kind: str = typer.Option("final", "--kind", "-k"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    Print the text of a specific chapter version to stdout.
    """
    repo = get_repo(project_root)
    text = repo.load_chapter_text(chapter_id, kind=kind, version=version)
    if text is None:
        typer.echo(f"No version v{version} found for {chapter_id} ({kind}).")
        raise typer.Exit(code=1)
    typer.echo(text)

@app.command("chapter-set-version")
def chapter_set_version(
    chapter_id: str = typer.Argument(..., help="Chapter ID, e.g. ch02"),
    version: int = typer.Argument(..., help="Version number to make current"),
    kind: str = typer.Option("final", "--kind", "-k"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    Make a specific chapter version the current one.

    Updates versions.json and the unversioned alias file.
    """
    repo = get_repo(project_root)

    # Optional sanity check: ensure the file exists
    text = repo.load_chapter_text(chapter_id, kind=kind, version=version)
    if text is None:
        typer.echo(f"No version v{version} found for {chapter_id} ({kind}).")
        raise typer.Exit(code=1)

    repo.set_current_chapter_version(chapter_id, kind, version)
    typer.echo(f"Set {chapter_id} ({kind}) to version v{version} as current.")

@app.command("bible-versions")
def bible_versions(
    section: str = typer.Argument(..., help="One of: characters, locations, items, timeline"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    List all versions for a bible section.
    """
    if section not in {"characters", "locations", "items", "timeline"}:
        raise typer.BadParameter("section must be one of: characters, locations, items, timeline")

    repo = get_repo(project_root)
    versions = repo.list_bible_versions(section)

    if not versions:
        typer.echo(f"No versions found for bible/{section}.")
        raise typer.Exit()

    typer.echo(f"Versions for bible/{section}:")
    for v in versions:
        ts = datetime.fromtimestamp(v.mtime).strftime("%Y-%m-%d %H:%M:%S")
        typer.echo(f"  v{v.version:02d}  {ts}  {v.path.name}")

@app.command("bible-show-version")
def bible_show_version(
    section: str = typer.Argument(..., help="characters|locations|items|timeline"),
    version: int = typer.Argument(..., help="Version number"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    Print the JSON for a specific bible section version.
    """
    repo = get_repo(project_root)
    txt = repo._load_versioned_text("bible", section, ".json", version)
    if txt is None:
        typer.echo(f"No version v{version} found for bible/{section}.")
        raise typer.Exit(code=1)
    typer.echo(txt)

@app.command("bible-set-version")
def bible_set_version(
    section: str = typer.Argument(..., help="characters|locations|items|timeline"),
    version: int = typer.Argument(..., help="Version number to make current"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    Make a specific bible section version the current one.
    """
    repo = get_repo(project_root)
    txt = repo._load_versioned_text("bible", section, ".json", version)
    if txt is None:
        typer.echo(f"No version v{version} found for bible/{section}.")
        raise typer.Exit(code=1)

    repo.set_current_bible_version(section, version)
    typer.echo(f"Set bible/{section} to version v{version} as current.")

@app.command("chapter-compare")
def chapter_compare(
    chapter_id: str = typer.Argument(...),
    v1: int = typer.Argument(..., help="First version"),
    v2: int = typer.Argument(..., help="Second version"),
    kind: str = typer.Option("final", "--kind", "-k"),
    project_root: Path = typer.Option(Path("."), "--project-root", "-r"),
):
    """
    Show two versions of a chapter one after the other for manual comparison.
    """
    repo = get_repo(project_root)
    t1 = repo.load_chapter_text(chapter_id, kind=kind, version=v1)
    t2 = repo.load_chapter_text(chapter_id, kind=kind, version=v2)

    if t1 is None or t2 is None:
        typer.echo("One of the versions was not found.")
        raise typer.Exit(code=1)

    typer.echo(f"===== {chapter_id} ({kind}) v{v1} =====")
    typer.echo(t1)
    typer.echo(f"\n\n===== {chapter_id} ({kind}) v{v2} =====")
    typer.echo(t2)

if __name__ == "__main__":
    app()
