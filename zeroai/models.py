from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Scene:
    index: int
    duration: int
    beat: str
    prompt: str
    status: str = "Planned"
    output_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        return cls(**data)


@dataclass
class Project:
    name: str = "Untitled Project"
    direction: str = ""
    style: str = "UGC / TikTok"
    aspect_ratio: str = "9:16"
    duration: int = 30
    references: list[str] = field(default_factory=list)
    scenes: list[Scene] = field(default_factory=list)
    final_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "scenes": [asdict(scene) for scene in self.scenes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        payload = dict(data)
        payload["scenes"] = [Scene.from_dict(item) for item in payload.get("scenes", [])]
        return cls(**payload)


@dataclass
class AppSettings:
    comfy_url: str = "http://127.0.0.1:8188"
    comfy_path: str = ""
    workflow_path: str = ""
    planner_mode: str = "Template"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    output_root: str = str(Path.home() / "Documents" / "ZeroAI")
    poll_interval_seconds: float = 2.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)
