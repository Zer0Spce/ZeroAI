from __future__ import annotations

import json
import os
from pathlib import Path

from .models import AppSettings, Project


APP_DIR = Path(os.getenv("LOCALAPPDATA", Path.home())) / "ZeroAI"
SETTINGS_FILE = APP_DIR / "settings.json"


def ensure_dirs(settings: AppSettings | None = None) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if settings:
        Path(settings.output_root).mkdir(parents=True, exist_ok=True)


def load_settings() -> AppSettings:
    ensure_dirs()
    if not SETTINGS_FILE.exists():
        settings = AppSettings()
        save_settings(settings)
        return settings
    try:
        return AppSettings.from_dict(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    ensure_dirs(settings)
    SETTINGS_FILE.write_text(json.dumps(settings.__dict__, indent=2), encoding="utf-8")


def save_project(project: Project, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(project.to_dict(), indent=2), encoding="utf-8")
    return target


def load_project(path: str | Path) -> Project:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Project.from_dict(data)
