from __future__ import annotations

import copy
import json
import random
import time
import uuid
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlencode

import requests

try:
    from websocket import WebSocketTimeoutException, create_connection
except ImportError:  # pragma: no cover - dependency is included in packaged builds
    WebSocketTimeoutException = TimeoutError
    create_connection = None

from .builtin_workflows import (
    AUDIO_VAE,
    BUILTIN_H3_URI,
    REF2VA_MODEL,
    TEXT_ENCODER,
    VIDEO_VAE,
    adapt_h3_canvas,
    align_h3_frames,
    build_h3_ref2va_workflow,
)


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str, poll_interval: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.session = requests.Session()
        self.client_id = f"zeroai-{uuid.uuid4().hex}"

    def system_stats(self) -> dict:
        response = self.session.get(self.base_url + "/system_stats", timeout=8)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def check(self) -> bool:
        try:
            self.system_stats()
            return True
        except requests.RequestException:
            return False

    def object_info(self, class_type: str) -> dict:
        response = self.session.get(self.base_url + f"/object_info/{class_type}", timeout=15)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _input_options(payload: dict, class_type: str, input_name: str) -> set[str]:
        node = payload.get(class_type, payload)
        config = node.get("input", {}).get("required", {}).get(input_name) if isinstance(node, dict) else None
        if isinstance(config, (list, tuple)) and config:
            values = config[0]
            if isinstance(values, (list, tuple)):
                return {str(value) for value in values}
        return set()

    def h3_readiness(self) -> dict:
        try:
            h3_info = self.object_info("MiniMaxH3ReferenceToVideo")
            node_available = "MiniMaxH3ReferenceToVideo" in h3_info
        except requests.RequestException:
            node_available = False
        if not node_available:
            return {
                "ready": False,
                "node_available": False,
                "missing": ["MiniMaxH3ReferenceToVideo node (update ComfyUI)"],
            }

        missing: list[str] = []
        checks = (
            ("VAELoader", "vae_name", VIDEO_VAE, "video VAE"),
            ("VAELoader", "vae_name", AUDIO_VAE, "audio VAE"),
            ("UNETLoader", "unet_name", REF2VA_MODEL, "Ref2VA diffusion model"),
            ("CLIPLoader", "clip_name", TEXT_ENCODER, "Qwen3-VL text encoder"),
        )
        cache: dict[str, dict] = {}
        for class_type, input_name, filename, label in checks:
            if class_type not in cache:
                try:
                    cache[class_type] = self.object_info(class_type)
                except requests.RequestException:
                    cache[class_type] = {}
            options = self._input_options(cache[class_type], class_type, input_name)
            if filename not in options:
                missing.append(f"{label}: {filename}")
        return {"ready": not missing, "node_available": True, "missing": missing}

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
            json={"prompt": workflow, "client_id": self.client_id},
            timeout=60,
        )
        if not response.ok:
            details = response.text[:1500]
            lower = details.lower()
            if "value_not_in_list" in lower and "minimax_h3" in lower:
                raise ComfyError(
                    "MiniMax H3 is not fully installed in ComfyUI. Open ZeroAI Settings → "
                    "MiniMax H3 Setup, click Download / Repair H3, then completely restart ComfyUI.\n\n"
                    f"ComfyUI validation: {details}"
                )
            raise ComfyError(f"ComfyUI rejected workflow: {response.status_code} {details}")
        prompt_id = response.json().get("prompt_id")
        if not prompt_id:
            raise ComfyError("ComfyUI did not return a prompt_id")
        return prompt_id

    def _websocket_url(self) -> str:
        if self.base_url.startswith("https://"):
            root = "wss://" + self.base_url[len("https://"):]
        elif self.base_url.startswith("http://"):
            root = "ws://" + self.base_url[len("http://"):]
        else:
            root = "ws://" + self.base_url
        return root + "/ws?clientId=" + self.client_id

    def _history_record(self, prompt_id: str) -> dict | None:
        response = self.session.get(self.base_url + f"/history/{prompt_id}", timeout=30)
        response.raise_for_status()
        payload = response.json()
        if prompt_id not in payload:
            return None
        record = payload[prompt_id]
        status = record.get("status", {})
        if status.get("status_str") == "error":
            messages = status.get("messages") or []
            detail = str(messages[-1])[:1200] if messages else ""
            raise ComfyError("ComfyUI generation failed" + (f": {detail}" if detail else ""))
        return record

    def wait(
        self,
        prompt_id: str,
        on_status: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int, str | None], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        """Wait for a prompt while streaming real sampler progress when available.

        ComfyUI sends sampler ``value/max`` updates over its websocket. History
        polling stays active as a fallback, so generation still works if a proxy,
        firewall, or older ComfyUI build prevents websocket progress events.
        """
        ws = None
        if create_connection is not None:
            try:
                ws = create_connection(self._websocket_url(), timeout=1.0, suppress_origin=True)
            except Exception:
                ws = None

        last_history = 0.0
        last_status = ""
        try:
            while True:
                if cancelled and cancelled():
                    raise ComfyError("Generation cancelled")

                if ws is not None:
                    try:
                        message = ws.recv()
                        if isinstance(message, str):
                            event = json.loads(message)
                            event_type = event.get("type")
                            data = event.get("data", {}) if isinstance(event, dict) else {}
                            event_prompt = data.get("prompt_id") if isinstance(data, dict) else None
                            if event_prompt and event_prompt != prompt_id:
                                continue
                            if event_type == "progress" and isinstance(data, dict):
                                value = int(data.get("value", 0) or 0)
                                maximum = int(data.get("max", 0) or 0)
                                node = data.get("node")
                                if maximum > 0 and on_progress:
                                    on_progress(value, maximum, str(node) if node is not None else None)
                            elif event_type in {"executing", "execution_start", "execution_cached"} and isinstance(data, dict):
                                node = data.get("node")
                                status_text = f"executing:{node}" if node is not None else "executing"
                                if on_status and status_text != last_status:
                                    last_status = status_text
                                    on_status(status_text)
                            elif event_type == "execution_error" and isinstance(data, dict):
                                message_text = data.get("exception_message") or data.get("exception_type") or "ComfyUI execution error"
                                raise ComfyError(str(message_text))
                    except WebSocketTimeoutException:
                        pass
                    except ComfyError:
                        raise
                    except Exception:
                        try:
                            ws.close()
                        except Exception:
                            pass
                        ws = None

                now = time.monotonic()
                if now - last_history >= self.poll_interval or ws is None:
                    record = self._history_record(prompt_id)
                    last_history = now
                    if record is not None:
                        if on_status:
                            on_status("complete")
                        return record
                    if on_status and not last_status:
                        on_status("generating")

                if ws is None:
                    time.sleep(min(self.poll_interval, 1.0))
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

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

        params = urlencode(
            {
                "filename": video["filename"],
                "subfolder": video.get("subfolder", ""),
                "type": video.get("type", "output"),
            }
        )
        response = self.session.get(self.base_url + "/view?" + params, timeout=300)
        response.raise_for_status()
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target


def load_workflow(path: str | Path) -> dict:
    raw = str(path or "").strip()
    if not raw or raw == BUILTIN_H3_URI:
        return build_h3_ref2va_workflow(9)
    source = Path(raw)
    if not source.exists():
        raise ComfyError(
            "The selected ComfyUI workflow file no longer exists. Open Settings and choose "
            "Use Built-in Workflow, or select another API workflow JSON."
        )
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


def _is_h3_workflow(template: dict) -> bool:
    return any(
        isinstance(node, dict) and node.get("class_type") == "MiniMaxH3ReferenceToVideo"
        for node in template.values()
    )


def _prune_unused_reference_nodes(workflow: dict) -> dict:
    removable: set[str] = set()
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            continue
        image = node.get("inputs", {}).get("image")
        if image in (None, ""):
            removable.add(str(node_id))
    for node_id in removable:
        workflow.pop(node_id, None)
    if not removable:
        return workflow

    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, value in list(inputs.items()):
            if isinstance(value, list) and len(value) >= 1 and str(value[0]) in removable:
                inputs.pop(key, None)
    return workflow


def prepare_workflow(
    template: dict,
    *,
    prompt: str,
    width: int,
    height: int,
    duration: int,
    references: list[str],
    seed: int | None = None,
    steps: int | None = None,
    h3_megapixels: float | None = None,
    ref_image_size: str = "match",
) -> dict:
    seed = seed if seed is not None else random.randint(1, 2_147_483_647)
    is_h3 = _is_h3_workflow(template)
    if is_h3:
        width, height = adapt_h3_canvas(width, height, h3_megapixels)
        frames = align_h3_frames(int(duration * 24))
    else:
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
    result = _replace(copy.deepcopy(template), replacements)

    if is_h3:
        effective_steps = min(100, max(1, int(steps if steps is not None else 20)))
        effective_ref_size = ref_image_size if ref_image_size in {"match", "max"} else "match"
        for node in result.values():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") == "BasicScheduler":
                node.setdefault("inputs", {})["steps"] = effective_steps
            elif node.get("class_type") == "MiniMaxH3ReferenceToVideo":
                node.setdefault("inputs", {})["ref_image_size"] = effective_ref_size
        return _prune_unused_reference_nodes(result)

    return result
