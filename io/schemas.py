# io/schemas.py
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Literal, Any
from pydantic import BaseModel


# ----- Core bible entities -----

@dataclass
class CharacterState:
    location: Optional[str] = None
    physical: List[str] = field(default_factory=list)
    restraints: List[str] = field(default_factory=list)
    emotional: List[str] = field(default_factory=list)
    knowledge: List[str] = field(default_factory=list)
    relationship_to: Dict[str, str] = field(default_factory=dict)  # name -> description


@dataclass
class CharacterRecord:
    name: str
    bio: str
    tags: List[str] = field(default_factory=list)  # ["POV", "antagonist", ...]
    current_state: CharacterState = field(default_factory=CharacterState)


@dataclass
class LocationRecord:
    name: str
    description: str
    tags: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class ItemRecord:
    name: str
    description: str
    owner: Optional[str] = None
    location: Optional[str] = None
    state: str = ""  # "new", "damaged", "destroyed", etc.
    tags: List[str] = field(default_factory=list)


@dataclass
class TimelineEvent:
    chapter_id: str
    order_in_chapter: int
    summary: str
    # you can add absolute dates later if you want


# ----- Bible container -----

@dataclass
class Bible:
    characters: Dict[str, CharacterRecord] = field(default_factory=dict)
    locations: Dict[str, LocationRecord] = field(default_factory=dict)
    items: Dict[str, ItemRecord] = field(default_factory=dict)
    timeline: List[TimelineEvent] = field(default_factory=list)


# ----- Chapter outline + summary -----

@dataclass
class ChapterOutline:
    chapter_id: str
    title: str
    pov: str
    target_word_count: int
    beats: List[str]
    must_include: List[str] = field(default_factory=list)
    avoid: List[str] = field(default_factory=list)


@dataclass
class ChapterSummary:
    chapter_id: str
    bullet_summary: List[str]
    character_updates: Dict[str, Dict[str, Any]]  # name -> partial state
    location_updates: Dict[str, Dict[str, Any]]
    item_updates: Dict[str, Dict[str, Any]]


# ----- Project config -----

@dataclass
class ProjectConfig:
    title: str
    author: str
    style_rules: List[str] = field(default_factory=list)
    tone: str = ""
    chapter_order: List[str] = field(default_factory=list)
    model_name: str | None = None


# helpers to jsonify dataclasses
def to_json_dict(obj) -> dict:
    return asdict(obj)
