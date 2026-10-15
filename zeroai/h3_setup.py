from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from .builtin_workflows import AUDIO_VAE, REF2VA_MODEL, TEXT_ENCODER, VIDEO_VAE


@dataclass(frozen=True)
class H3ModelFile:
    label: str
    folder: str
    filename: str
    url: str
    expected_bytes: int
    min_ready_bytes: int


H3_MODEL_FILES: tuple[H3ModelFile, ...] = (
    H3ModelFile(
        "Ref2VA diffusion model",
        "diffusion_models",
        REF2VA_MODEL,
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
        21_000_000_000,
        18_000_000_000,
    ),
    H3ModelFile(
        "Qwen3-VL text encoder",
        "text_encoders",
        TEXT_ENCODER,
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        15_700_000_000,
        13_000_000_000,
    ),
    H3ModelFile(
        "Video VAE",
        "vae",
        VIDEO_VAE,
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors",
        5_210_000_000,
        4_500_000_000,
    ),
    H3ModelFile(
        "Audio VAE",
        "vae",
        AUDIO_VAE,
        "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors",
        605_000_000,
        500_000_000,
    ),
)

TOTAL_EXPECTED_BYTES = sum(item.expected_bytes for item in H3_MODEL_FILES)


class H3SetupError(RuntimeError):
    pass


class H3DownloadCancelled(H3SetupError):
    pass


def format_bytes(value: int | float) -> str:
    value = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1000
    return f"{value:.1f} TB"


def normalize_comfyui_root(path: str | Path | None) -> Path | None:
    if not path:
        return None
    root = Path(os.path.expandvars(os.path.expanduser(str(path).strip().strip('"'))))
    candidates = [root, root / "ComfyUI"]
    for candidate in candidates:
        if (candidate / "models").is_dir() or (candidate / "main.py").is_file():
            return candidate
    return root if root.exists() else None


def detect_comfyui_root(preferred: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if preferred:
        candidates.append(Path(str(preferred)))
    env_path = os.environ.get("COMFYUI_PATH")
    if env_path:
        candidates.append(Path(env_path))

    home = Path.home()
    bases = [
        Path("C:/ComfyUI"),
        Path("C:/AI/ComfyUI"),
        home / "ComfyUI",
        home / "Desktop" / "ComfyUI",
        home / "Documents" / "ComfyUI",
        home / "Downloads" / "ComfyUI",
        home / "Desktop" / "ComfyUI_windows_portable" / "ComfyUI",
        home / "Downloads" / "ComfyUI_windows_portable" / "ComfyUI",
        home / "Documents" / "ComfyUI_windows_portable" / "ComfyUI",
    ]
    candidates.extend(bases)

    seen: set[str] = set()
    for raw in candidates:
        normalized = normalize_comfyui_root(raw)
        if not normalized:
            continue
        key = str(normalized).lower()
        if key in seen:
            continue
        seen.add(key)
        if (normalized / "models").is_dir() and ((normalized / "main.py").is_file() or normalized.name.lower() == "comfyui"):
            return normalized
    return None


def model_destination(comfy_root: str | Path, model: H3ModelFile) -> Path:
    return Path(comfy_root) / "models" / model.folder / model.filename


def model_status(comfy_root: str | Path | None) -> dict[str, dict]:
    if not comfy_root:
        return {
            item.filename: {"ready": False, "exists": False, "size": 0, "path": ""}
            for item in H3_MODEL_FILES
        }
    root = Path(comfy_root)
    result: dict[str, dict] = {}
    for item in H3_MODEL_FILES:
        path = model_destination(root, item)
        size = path.stat().st_size if path.exists() else 0
        result[item.filename] = {
            "ready": size >= item.min_ready_bytes,
            "exists": path.exists(),
            "size": size,
            "path": str(path),
            "label": item.label,
        }
    return result


def missing_models(comfy_root: str | Path | None) -> list[H3ModelFile]:
    status = model_status(comfy_root)
    return [item for item in H3_MODEL_FILES if not status[item.filename]["ready"]]


def is_h3_installed(comfy_root: str | Path | None) -> bool:
    return bool(comfy_root) and not missing_models(comfy_root)


def remaining_download_bytes(comfy_root: str | Path | None) -> int:
    status = model_status(comfy_root)
    remaining = 0
    for item in H3_MODEL_FILES:
        current = status[item.filename]["size"]
        if current >= item.min_ready_bytes:
            continue
        part = model_destination(comfy_root, item).with_suffix(model_destination(comfy_root, item).suffix + ".part") if comfy_root else None
        partial_size = part.stat().st_size if part and part.exists() else 0
        remaining += max(0, item.expected_bytes - max(current, partial_size))
    return remaining


def _prepare_partial(target: Path, min_ready_bytes: int) -> Path:
    part = target.with_suffix(target.suffix + ".part")
    if target.exists() and target.stat().st_size < min_ready_bytes:
        if part.exists():
            if target.stat().st_size > part.stat().st_size:
                part.unlink()
                target.replace(part)
            else:
                target.unlink()
        else:
            target.replace(part)
    return part


def _download_one(
    session: requests.Session,
    item: H3ModelFile,
    target: Path,
    *,
    file_index: int,
    file_count: int,
    progress: Callable[[int, str], None] | None,
    log: Callable[[str], None] | None,
    cancelled: Callable[[], bool] | None,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size >= item.min_ready_bytes:
        if log:
            log(f"{item.label}: already installed — {target.name}")
        if progress:
            progress(int(((file_index + 1) / file_count) * 100), f"{item.label}: already installed")
        return

    part = _prepare_partial(target, item.min_ready_bytes)
    last_error: Exception | None = None
    for attempt in range(1, 4):
        if cancelled and cancelled():
            raise H3DownloadCancelled("MiniMax H3 download cancelled")
        resume_at = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "ZeroAI/0.2 Windows"}
        if resume_at:
            headers["Range"] = f"bytes={resume_at}-"
        try:
            if log:
                verb = "Resuming" if resume_at else "Downloading"
                log(f"{verb} {item.label} ({target.name})")
            response = session.get(
                item.url,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=(20, 180),
            )
            if response.status_code not in (200, 206):
                raise H3SetupError(f"HTTP {response.status_code} while downloading {item.filename}")

            append = resume_at > 0 and response.status_code == 206
            if not append and resume_at:
                resume_at = 0
            content_length = int(response.headers.get("Content-Length", "0") or 0)
            total = resume_at + content_length if content_length else item.expected_bytes
            mode = "ab" if append else "wb"
            downloaded = resume_at
            with part.open(mode) as fh:
                for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                    if cancelled and cancelled():
                        raise H3DownloadCancelled("MiniMax H3 download cancelled")
                    if not chunk:
                        continue
                    fh.write(chunk)
                    downloaded += len(chunk)
                    fraction = min(1.0, downloaded / max(1, total))
                    overall = int(((file_index + fraction) / file_count) * 100)
                    if progress:
                        progress(overall, f"{item.label}: {format_bytes(downloaded)} / {format_bytes(total)}")
            if part.stat().st_size < item.min_ready_bytes:
                raise H3SetupError(f"Download for {item.filename} looks incomplete ({format_bytes(part.stat().st_size)}).")
            if target.exists():
                target.unlink()
            part.replace(target)
            if log:
                log(f"Installed {item.label}: {target}")
            return
        except H3DownloadCancelled:
            raise
        except (requests.RequestException, OSError, H3SetupError) as exc:
            last_error = exc
            if log:
                log(f"Download attempt {attempt}/3 failed for {item.label}: {exc}")
            if attempt >= 3:
                break
    raise H3SetupError(str(last_error or f"Could not download {item.filename}"))


def install_h3_models(
    comfy_root: str | Path,
    *,
    progress: Callable[[int, str], None] | None = None,
    log: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    root = normalize_comfyui_root(comfy_root)
    if not root or not root.exists():
        raise H3SetupError("Choose your ComfyUI folder first.")
    models_dir = root / "models"
    if not models_dir.exists():
        raise H3SetupError(f"This does not look like a ComfyUI folder: {root}")

    remaining = remaining_download_bytes(root)
    free = shutil.disk_usage(root).free
    reserve = 2_000_000_000
    if free < remaining + reserve:
        raise H3SetupError(
            f"Not enough free disk space. Need about {format_bytes(remaining + reserve)}, "
            f"but only {format_bytes(free)} is free."
        )

    session = requests.Session()
    session.headers.update({"Accept-Encoding": "identity"})
    for index, item in enumerate(H3_MODEL_FILES):
        _download_one(
            session,
            item,
            model_destination(root, item),
            file_index=index,
            file_count=len(H3_MODEL_FILES),
            progress=progress,
            log=log,
            cancelled=cancelled,
        )
    if progress:
        progress(100, "MiniMax H3 models installed")
