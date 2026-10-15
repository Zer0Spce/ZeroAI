from __future__ import annotations

import json
import os
import re
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
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"


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


def _expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value).strip().strip('"').strip("'"))))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _models_root_from_candidate(path: str | Path | None) -> Path | None:
    if not path:
        return None
    root = _expand_path(path)
    if root.name.lower() == "models":
        return root if root.exists() else None
    if (root / "models").is_dir():
        return root / "models"
    # Shared/custom model roots can be named anything. Recognize them by
    # canonical ComfyUI subdirectories rather than requiring the name 'models'.
    if root.is_dir() and any((root / name).is_dir() for name in ("vae", "diffusion_models", "text_encoders", "checkpoints")):
        return root
    return None


def _storage_root_from_models_root(models_root: Path) -> Path:
    return models_root.parent if models_root.name.lower() == "models" else models_root


def _cli_values(argv: list[str], flag: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(argv):
        token = str(argv[index])
        if token == flag:
            index += 1
            while index < len(argv) and not str(argv[index]).startswith("--"):
                values.append(str(argv[index]))
                index += 1
            continue
        prefix = flag + "="
        if token.startswith(prefix):
            raw = token[len(prefix):]
            if raw:
                values.append(raw)
        index += 1
    return values


def _yaml_model_roots(path: Path) -> list[tuple[Path, bool]]:
    """Read base_path entries from ComfyUI extra-model-path YAML without PyYAML."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    result: list[tuple[Path, bool]] = []
    current_base: Path | None = None
    current_default = False

    def flush() -> None:
        nonlocal current_base, current_default
        if current_base is not None:
            result.append((current_base, current_default))
        current_base = None
        current_default = False

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line and not raw_line[0].isspace() and raw_line.rstrip().endswith(":"):
            flush()
            continue
        stripped = raw_line.strip()
        match = re.match(r"base_path\s*:\s*(.+)$", stripped, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip().strip('"').strip("'")
            if value:
                current_base = _expand_path(value)
            continue
        if re.match(r"is_default\s*:\s*true\s*$", stripped, flags=re.IGNORECASE):
            current_default = True
    flush()
    return result


def runtime_model_roots_from_stats(stats: dict) -> list[Path]:
    """Resolve model roots from the actual ComfyUI process launch arguments."""
    system = stats.get("system", {}) if isinstance(stats, dict) else {}
    raw_argv = system.get("argv", []) if isinstance(system, dict) else []
    argv = [str(value) for value in raw_argv] if isinstance(raw_argv, list) else []
    if not argv:
        return []

    explicit_roots: list[Path] = []
    for value in _cli_values(argv, "--models-directory"):
        path = _expand_path(value)
        if path.is_dir():
            explicit_roots.append(path)

    yaml_roots: list[tuple[Path, bool]] = []
    for value in _cli_values(argv, "--extra-model-paths-config"):
        config = _expand_path(value)
        yaml_roots.extend(_yaml_model_roots(config))

    primary_yaml = [path for path, is_default in yaml_roots if is_default and path.is_dir()]
    other_yaml = [path for path, is_default in yaml_roots if not is_default and path.is_dir()]

    builtin_roots: list[Path] = []
    base_values = _cli_values(argv, "--base-directory")
    if base_values:
        base_models = _expand_path(base_values[-1]) / "models"
        if base_models.is_dir():
            builtin_roots.append(base_models)
    elif argv:
        entry = _expand_path(argv[0])
        if entry.is_absolute() and entry.name.lower() == "main.py":
            base_models = entry.parent / "models"
            if base_models.is_dir():
                builtin_roots.append(base_models)

    ordered = explicit_roots + primary_yaml + builtin_roots + other_yaml
    seen: set[str] = set()
    result: list[Path] = []
    for root in ordered:
        key = str(root.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(root)
    return result


def runtime_model_roots(comfy_url: str = DEFAULT_COMFY_URL) -> list[Path]:
    try:
        response = requests.get(comfy_url.rstrip("/") + "/system_stats", timeout=3)
        response.raise_for_status()
        payload = response.json()
        return runtime_model_roots_from_stats(payload if isinstance(payload, dict) else {})
    except (requests.RequestException, ValueError, TypeError):
        return []


def _desktop_config_model_roots() -> list[Path]:
    """Fallback discovery for both current Comfy Desktop and legacy Desktop."""
    home = Path.home()
    appdata = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
    localappdata = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
    roots: list[Path] = []

    # Current Comfy Desktop stores shared model dirs in settings.json.
    for config_dir in (appdata / "Comfy Desktop", appdata / "comfyui-desktop-2"):
        settings = _read_json(config_dir / "settings.json")
        if isinstance(settings, dict):
            model_dirs = settings.get("modelsDirs")
            if isinstance(model_dirs, list):
                for value in model_dirs:
                    if isinstance(value, str):
                        candidate = _models_root_from_candidate(value)
                        if candidate:
                            roots.append(candidate)

        installations = _read_json(config_dir / "installations.json")
        records = installations if isinstance(installations, list) else []
        if isinstance(installations, dict):
            maybe_records = installations.get("installations")
            if isinstance(maybe_records, list):
                records = maybe_records
        local_records = [item for item in records if isinstance(item, dict) and isinstance(item.get("installPath"), str)]
        local_records.sort(key=lambda item: int(item.get("lastLaunchedAt") or 0), reverse=True)
        for item in local_records:
            primary = item.get("modelDirsPrimary")
            if isinstance(primary, str):
                candidate = _models_root_from_candidate(primary)
                if candidate:
                    roots.append(candidate)
            model_dirs = item.get("modelDirs")
            if isinstance(model_dirs, list):
                for value in model_dirs:
                    if isinstance(value, str):
                        candidate = _models_root_from_candidate(value)
                        if candidate:
                            roots.append(candidate)
            install_path = _expand_path(item["installPath"])
            for candidate_path in (install_path / "ComfyUI" / "models", install_path / "models"):
                if candidate_path.is_dir():
                    roots.append(candidate_path)

    # Legacy ComfyUI Desktop stores the selected workspace in config.json.
    legacy = _read_json(appdata / "ComfyUI" / "config.json")
    if isinstance(legacy, dict):
        base_path = legacy.get("basePath")
        if isinstance(base_path, str):
            candidate = _models_root_from_candidate(base_path)
            if candidate:
                roots.append(candidate)

    # Current Desktop defaults. Include both new LocalAppData layout and the
    # legacy home-root layout retained for upgraded installs.
    for candidate_path in (
        localappdata / "Comfy-Desktop" / "ComfyUI-Shared" / "models",
        home / "ComfyUI-Shared" / "models",
    ):
        if candidate_path.is_dir():
            roots.append(candidate_path)

    seen: set[str] = set()
    result: list[Path] = []
    for root in roots:
        try:
            key = str(root.resolve()).lower()
        except OSError:
            key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(root)
    return result


def discover_model_roots(preferred: str | Path | None = None, comfy_url: str = DEFAULT_COMFY_URL) -> list[Path]:
    roots: list[Path] = []
    roots.extend(runtime_model_roots(comfy_url))
    roots.extend(_desktop_config_model_roots())
    preferred_root = _models_root_from_candidate(preferred)
    if preferred_root:
        roots.append(preferred_root)

    home = Path.home()
    for raw in (
        Path("C:/ComfyUI"),
        Path("C:/AI/ComfyUI"),
        home / "ComfyUI",
        home / "Desktop" / "ComfyUI",
        home / "Documents" / "ComfyUI",
        home / "Downloads" / "ComfyUI",
        home / "Desktop" / "ComfyUI_windows_portable" / "ComfyUI",
        home / "Downloads" / "ComfyUI_windows_portable" / "ComfyUI",
        home / "Documents" / "ComfyUI_windows_portable" / "ComfyUI",
    ):
        candidate = _models_root_from_candidate(raw)
        if candidate:
            roots.append(candidate)

    seen: set[str] = set()
    result: list[Path] = []
    for root in roots:
        try:
            key = str(root.resolve()).lower()
        except OSError:
            key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(root)
    return result


def normalize_comfyui_root(path: str | Path | None, comfy_url: str = DEFAULT_COMFY_URL) -> Path | None:
    # If ComfyUI is running, its actual launch arguments are the source of truth.
    runtime = runtime_model_roots(comfy_url)
    if runtime:
        return _storage_root_from_models_root(runtime[0])

    models_root = _models_root_from_candidate(path)
    if models_root:
        return _storage_root_from_models_root(models_root)

    if not path:
        return None
    root = _expand_path(path)
    candidates = [root, root / "ComfyUI"]
    for candidate in candidates:
        if (candidate / "models").is_dir() or (candidate / "main.py").is_file():
            return candidate
    return root if root.exists() else None


def detect_comfyui_root(preferred: str | Path | None = None, comfy_url: str = DEFAULT_COMFY_URL) -> Path | None:
    roots = discover_model_roots(preferred, comfy_url)
    if roots:
        return _storage_root_from_models_root(roots[0])
    return normalize_comfyui_root(preferred, comfy_url)


def _resolve_models_root(comfy_root: str | Path | None, comfy_url: str = DEFAULT_COMFY_URL) -> Path | None:
    runtime = runtime_model_roots(comfy_url)
    if runtime:
        return runtime[0]
    return _models_root_from_candidate(comfy_root)


def model_destination(comfy_root: str | Path, model: H3ModelFile, comfy_url: str = DEFAULT_COMFY_URL) -> Path:
    models_root = _resolve_models_root(comfy_root, comfy_url)
    if not models_root:
        root = _expand_path(comfy_root)
        models_root = root if root.name.lower() == "models" else root / "models"
    return models_root / model.folder / model.filename


def model_status(comfy_root: str | Path | None, comfy_url: str = DEFAULT_COMFY_URL) -> dict[str, dict]:
    models_root = _resolve_models_root(comfy_root, comfy_url)
    if not models_root:
        return {
            item.filename: {"ready": False, "exists": False, "size": 0, "path": ""}
            for item in H3_MODEL_FILES
        }
    result: dict[str, dict] = {}
    for item in H3_MODEL_FILES:
        path = models_root / item.folder / item.filename
        size = path.stat().st_size if path.exists() else 0
        result[item.filename] = {
            "ready": size >= item.min_ready_bytes,
            "exists": path.exists(),
            "size": size,
            "path": str(path),
            "label": item.label,
        }
    return result


def missing_models(comfy_root: str | Path | None, comfy_url: str = DEFAULT_COMFY_URL) -> list[H3ModelFile]:
    status = model_status(comfy_root, comfy_url)
    return [item for item in H3_MODEL_FILES if not status[item.filename]["ready"]]


def is_h3_installed(comfy_root: str | Path | None, comfy_url: str = DEFAULT_COMFY_URL) -> bool:
    return bool(comfy_root) and not missing_models(comfy_root, comfy_url)


def remaining_download_bytes(comfy_root: str | Path | None, comfy_url: str = DEFAULT_COMFY_URL) -> int:
    status = model_status(comfy_root, comfy_url)
    remaining = 0
    for item in H3_MODEL_FILES:
        current = status[item.filename]["size"]
        if current >= item.min_ready_bytes:
            continue
        part = model_destination(comfy_root, item, comfy_url).with_suffix(
            model_destination(comfy_root, item, comfy_url).suffix + ".part"
        ) if comfy_root else None
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


def _reuse_existing_downloads(
    target_models_root: Path,
    *,
    preferred: str | Path | None,
    comfy_url: str,
    log: Callable[[str], None] | None,
) -> None:
    """Reuse v0.2 downloads placed in a model folder Desktop is not indexing."""
    candidates = discover_model_roots(preferred, comfy_url)
    for item in H3_MODEL_FILES:
        target = target_models_root / item.folder / item.filename
        if target.exists() and target.stat().st_size >= item.min_ready_bytes:
            continue
        for source_root in candidates:
            source = source_root / item.folder / item.filename
            try:
                if source.resolve() == target.resolve():
                    continue
            except OSError:
                pass
            if not source.exists() or source.stat().st_size < item.min_ready_bytes:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, target)
                if log:
                    log(f"Reused existing {item.label} with an NTFS hard link: {source}")
            except OSError:
                try:
                    shutil.move(str(source), str(target))
                    if log:
                        log(f"Moved existing {item.label} into ComfyUI Desktop's active model library.")
                except OSError as exc:
                    if log:
                        log(f"Could not reuse existing {item.label} from {source}: {exc}")
                    continue
            break


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
        headers = {"User-Agent": "ZeroAI/0.2.1 Windows"}
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
    comfy_url: str = DEFAULT_COMFY_URL,
    progress: Callable[[int, str], None] | None = None,
    log: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    models_root = _resolve_models_root(comfy_root, comfy_url)
    if not models_root:
        root = normalize_comfyui_root(comfy_root, comfy_url)
        models_root = _models_root_from_candidate(root)
    if not models_root or not models_root.exists():
        raise H3SetupError("ZeroAI could not resolve the model library used by the running ComfyUI instance.")

    if log:
        log(f"Active ComfyUI model library: {models_root}")

    _reuse_existing_downloads(
        models_root,
        preferred=comfy_root,
        comfy_url=comfy_url,
        log=log,
    )

    remaining = 0
    for item in H3_MODEL_FILES:
        target = models_root / item.folder / item.filename
        if target.exists() and target.stat().st_size >= item.min_ready_bytes:
            continue
        part = target.with_suffix(target.suffix + ".part")
        partial_size = part.stat().st_size if part.exists() else 0
        remaining += max(0, item.expected_bytes - partial_size)

    free = shutil.disk_usage(models_root).free
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
            models_root / item.folder / item.filename,
            file_index=index,
            file_count=len(H3_MODEL_FILES),
            progress=progress,
            log=log,
            cancelled=cancelled,
        )
    if progress:
        progress(100, "MiniMax H3 models installed")
