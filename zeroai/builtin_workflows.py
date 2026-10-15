from __future__ import annotations

import json
import math
import os
from pathlib import Path

BUILTIN_H3_URI = "builtin://minimax-h3-ref2va"
BUILTIN_H3_NAME = "MiniMax H3 Ref2VA — ZeroAI adaptive 1–9 references"

VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
REF2VA_MODEL = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"

H3_NATIVE_MEGAPIXELS = 0.98
H3_NATIVE_MAX_PIXELS = 768 * 1344


def align_h3_frames(frame_count: int) -> int:
    """Snap a frame count up to MiniMax H3's 17k+5 grid."""
    n = max(5, int(frame_count))
    return n + (5 - (n % 17)) % 17


def adapt_h3_canvas(width: int, height: int, megapixels: float | None = None) -> tuple[int, int]:
    """Build an H3 canvas on the 32px grid.

    With ``megapixels=None`` this preserves the previous native-canvas behavior
    (768px short edge / roughly 0.98 MP). A lower megapixel target is useful for
    fast previews and low-VRAM machines.
    """
    width = max(32, int(width))
    height = max(32, int(height))
    ratio = width / height

    if megapixels is not None:
        target_pixels = max(32 * 32, float(megapixels) * 1024 * 1024)
        target_pixels = min(float(H3_NATIVE_MAX_PIXELS), target_pixels)
        nominal_h = math.sqrt(target_pixels / ratio)
        nominal_w = nominal_h * ratio
    else:
        base_short_edge = 768
        if ratio >= 1.0:
            nominal_w, nominal_h = base_short_edge * ratio, base_short_edge
        else:
            nominal_w, nominal_h = base_short_edge, base_short_edge / ratio
        if nominal_w * nominal_h > H3_NATIVE_MAX_PIXELS:
            scale = math.sqrt(H3_NATIVE_MAX_PIXELS / (nominal_w * nominal_h))
            nominal_w *= scale
            nominal_h *= scale

    out_w = max(32, round(nominal_w / 32) * 32)
    out_h = max(32, round(nominal_h / 32) * 32)
    return out_w, out_h


def build_h3_ref2va_workflow(reference_count: int = 9) -> dict:
    """Build a compact ComfyUI API-format MiniMax H3 Ref2VA graph."""
    reference_count = min(9, max(1, int(reference_count)))
    workflow: dict[str, dict] = {
        "92": {
            "inputs": {
                "filename_prefix": "video/ZeroAI_MiniMax_H3",
                "format": "auto",
                "codec": "auto",
                "video": ["130", 0],
            },
            "class_type": "SaveVideo",
            "_meta": {"title": "Save ZeroAI H3 Video"},
        },
        "119": {
            "inputs": {"vae_name": VIDEO_VAE},
            "class_type": "VAELoader",
            "_meta": {"title": "MiniMax H3 Video VAE"},
        },
        "120": {
            "inputs": {"vae_name": AUDIO_VAE},
            "class_type": "VAELoader",
            "_meta": {"title": "MiniMax H3 Audio VAE"},
        },
        "121": {
            "inputs": {"samples": ["125", 0], "vae": ["120", 0]},
            "class_type": "VAEDecodeAudio",
            "_meta": {"title": "Decode H3 Audio"},
        },
        "122": {
            "inputs": {"samples": ["125", 0], "vae": ["119", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "Decode H3 Video"},
        },
        "123": {
            "inputs": {"sampler_name": "res_multistep"},
            "class_type": "KSamplerSelect",
            "_meta": {"title": "H3 Sampler"},
        },
        "124": {
            "inputs": {
                "scheduler": "simple",
                "steps": 20,
                "denoise": 1.0,
                "model": ["127", 0],
            },
            "class_type": "BasicScheduler",
            "_meta": {"title": "H3 Scheduler"},
        },
        "125": {
            "inputs": {
                "noise": ["129", 0],
                "guider": ["126", 0],
                "sampler": ["123", 0],
                "sigmas": ["124", 0],
                "latent_image": ["136", 1],
            },
            "class_type": "SamplerCustomAdvanced",
            "_meta": {"title": "Sample H3"},
        },
        "126": {
            "inputs": {"model": ["127", 0], "conditioning": ["136", 0]},
            "class_type": "BasicGuider",
            "_meta": {"title": "H3 Guider"},
        },
        "127": {
            "inputs": {"unet_name": REF2VA_MODEL, "weight_dtype": "default"},
            "class_type": "UNETLoader",
            "_meta": {"title": "MiniMax H3 Ref2VA Model"},
        },
        "128": {
            "inputs": {
                "clip_name": TEXT_ENCODER,
                "type": "minimax",
                "device": "default",
            },
            "class_type": "CLIPLoader",
            "_meta": {"title": "MiniMax H3 Text Encoder"},
        },
        "129": {
            "inputs": {"noise_seed": "{{SEED}}"},
            "class_type": "RandomNoise",
            "_meta": {"title": "ZeroAI Seed"},
        },
        "130": {
            "inputs": {
                "fps": 24,
                "bit_depth": 8,
                "images": ["122", 0],
                "audio": ["121", 0],
            },
            "class_type": "CreateVideo",
            "_meta": {"title": "Create H3 Video + Audio"},
        },
        "136": {
            "inputs": {
                "prompt": "{{PROMPT}}",
                "width": "{{WIDTH}}",
                "height": "{{HEIGHT}}",
                "length": "{{FRAMES}}",
                "ref_image_size": "match",
                "clip": ["128", 0],
                "vae": ["119", 0],
                "audio_vae": ["120", 0],
            },
            "class_type": "MiniMaxH3ReferenceToVideo",
            "_meta": {"title": "MiniMax H3 Reference to Video"},
        },
    }

    for index in range(reference_count):
        node_id = str(300 + index)
        workflow[node_id] = {
            "inputs": {"image": f"{{{{REFERENCE_{index + 1}}}}}"},
            "class_type": "LoadImage",
            "_meta": {"title": f"ZeroAI Reference {index + 1}"},
        }
        workflow["136"]["inputs"][f"ref_images.ref_image_{index}"] = [node_id, 0]
    return workflow


def local_workflow_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "ZeroAI" / "workflows"


def write_builtin_workflow_files(destination: str | Path | None = None) -> list[Path]:
    """Expose ready-to-use API JSONs on disk for users and advanced editing."""
    target = Path(destination) if destination else local_workflow_dir()
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for count in range(1, 10):
        path = target / f"minimax_h3_ref2va_zeroai_{count}ref_api.json"
        payload = json.dumps(build_h3_ref2va_workflow(count), indent=2, ensure_ascii=False)
        if not path.exists() or path.read_text(encoding="utf-8") != payload:
            path.write_text(payload, encoding="utf-8")
        written.append(path)
    return written
