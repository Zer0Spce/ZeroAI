from __future__ import annotations

import copy
import json
import random
import time
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlencode

import requests


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str, poll_interval: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.session = requests.Session()

    def check(self) -> bool:
        try:
            response = self.session.get(self.base_url + "/system_stats", timeout=4)
            return response.ok
        except requests.RequestException:
            return False

    def upload_image(self, path: str | Path) -> str:
        source = Path(path)
        with source.open("rb") as fh:
            response = self.session.post(
                self.base_url + "/upload/image",
                files={"image": (source.name, fh, "application/octet-stream")},
                data={"overwrite": "true"},
                timeout=120,
            )
        response.raise_for_status()
        data = response.json()
        subfolder = data.get("subfolder", "")
        name = data.get("name", source.name)
        return f"{subfolder}/{name}".strip("/")

    def queue(self, workflow: dict) -> str:
        response = self.session.post(
            self.base_url + "/prompt",
            json={"prompt": workflow, "client_id": "zeroai-windows"},
            timeout=60,
        )
        if not response.ok:
            raise ComfyError(f"ComfyUI rejected workflow: {response.status_code} {response.text[:500]}")
        prompt_id = response.json().get("prompt_id")
        if not prompt_id:
            raise ComfyError("ComfyUI did not return a prompt_id")
        return prompt_id

    def wait(self, prompt_id: str, on_status: Callable[[str], None] | None = None, cancelled: Callable[[], bool] | None = None) -> dict:
        while True:
            if cancelled and cancelled():
                raise ComfyError("Generation cancelled")
            response = self.session.get(self.base_url + f"/history/{prompt_id}", timeout=30)
            response.raise_for_status()
            payload = response.json()
            if prompt_id in payload:
                record = payload[prompt_id]
                status = record.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError("ComfyUI generation failed")
                if on_status:
                    on_status(status.get("status_str", "complete"))
                return record
            if on_status:
                on_status("generating")
            time.sleep(self.poll_interval)

    @staticmethod
    def _output_candidates(record: dict) -> Iterable[dict]:
        for node in record.get("outputs", {}).values():
            for key in ("videos", "gifs", "images", "audio"):
                for item in node.get(key, []) or []:
                    if isinstance(item, dict) and item.get("filename"):
                        yield item

    def download_video(self, record: dict, destination: str | Path) -> Path:
        video = None
        for item in self._output_candidates(record):
            suffix = Path(item.get("filename", "")).suffix.lower()
            if suffix in {".mp4", ".webm", ".mov", ".mkv"}:
                video = item
                break
        if not video:
            raise ComfyError("No video file was found in ComfyUI's outputs")

        params = urlencode({
            "filename": video["filename"],
            "subfolder": video.get("subfolder", ""),
            "type": video.get("type", "output"),
        })
        response = self.session.get(self.base_url + "/view?" + params, timeout=300)
        response.raise_for_status()
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target


def load_workflow(path: str | Path) -> dict:
    source = Path(path)
    if not source.exists():
        raise ComfyError("Select a ComfyUI API workflow JSON in Settings first")
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ComfyError("Workflow JSON must be an object")
    return data.get("prompt", data)


def _replace(value, replacements: dict[str, object]):
    if isinstance(value, dict):
        return {k: _replace(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace(v, replacements) for v in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped in replacements:
            return replacements[stripped]
        result = value
        for token, replacement in replacements.items():
            result = result.replace(token, str(replacement))
        return result
    return value


def prepare_workflow(template: dict, *, prompt: str, width: int, height: int, duration: int, references: list[str], seed: int | None = None) -> dict:
    seed = seed if seed is not None else random.randint(1, 2_147_483_647)
    frames = max(1, int(duration * 24))
    replacements: dict[str, object] = {
        "{{PROMPT}}": prompt,
        "{{WIDTH}}": width,
        "{{HEIGHT}}": height,
        "{{DURATION}}": duration,
        "{{FRAMES}}": frames,
        "{{SEED}}": seed,
    }
    for i in range(1, 10):
        replacements[f"{{{{REFERENCE_{i}}}}}"] = references[i - 1] if i <= len(references) else ""
    return _replace(copy.deepcopy(template), replacements)
