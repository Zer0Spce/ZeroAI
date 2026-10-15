from __future__ import annotations

from dataclasses import dataclass
from typing import Any


AUTO_PRESET = "Auto (GPU-aware)"
LOW_VRAM_PRESET = "RTX 3060 Laptop / Low VRAM"
FAST_PRESET = "Fast Preview"
BALANCED_PRESET = "Balanced"
NATIVE_PRESET = "Native Quality"
CUSTOM_PRESET = "Custom"

PRESET_NAMES = [
    AUTO_PRESET,
    LOW_VRAM_PRESET,
    FAST_PRESET,
    BALANCED_PRESET,
    NATIVE_PRESET,
    CUSTOM_PRESET,
]

RESOLUTION_OPTIONS = [
    ("0.40 MP — Fast / low VRAM", 0.40),
    ("0.70 MP — Balanced", 0.70),
    ("0.90 MP — High", 0.90),
    ("0.98 MP — H3 native", 0.98),
]


@dataclass(frozen=True)
class H3PerformanceProfile:
    name: str
    megapixels: float
    steps: int
    max_references: int
    ref_image_size: str = "match"
    note: str = ""


LOW_VRAM_PROFILE = H3PerformanceProfile(
    LOW_VRAM_PRESET,
    0.40,
    12,
    3,
    "match",
    "Recommended for laptop GPUs around 6–8 GB VRAM and 16 GB system RAM.",
)
FAST_PROFILE = H3PerformanceProfile(
    FAST_PRESET,
    0.40,
    8,
    2,
    "match",
    "Fastest preview. Lower step count can reduce identity/motion fidelity.",
)
BALANCED_PROFILE = H3PerformanceProfile(
    BALANCED_PRESET,
    0.70,
    16,
    4,
    "match",
    "Good middle ground for speed and detail.",
)
NATIVE_PROFILE = H3PerformanceProfile(
    NATIVE_PRESET,
    0.98,
    20,
    9,
    "match",
    "H3 native canvas and official base step count. Slow on low-VRAM laptops.",
)

STATIC_PRESETS = {
    LOW_VRAM_PRESET: LOW_VRAM_PROFILE,
    FAST_PRESET: FAST_PROFILE,
    BALANCED_PRESET: BALANCED_PROFILE,
    NATIVE_PRESET: NATIVE_PROFILE,
}


def _gb(value: Any) -> float:
    try:
        return float(value) / (1024 ** 3)
    except (TypeError, ValueError):
        return 0.0


def hardware_info(system_stats: dict | None) -> tuple[float, float, str]:
    payload = system_stats or {}
    system = payload.get("system", {}) if isinstance(payload, dict) else {}
    devices = payload.get("devices", []) if isinstance(payload, dict) else []
    ram_gb = _gb(system.get("ram_total")) if isinstance(system, dict) else 0.0
    vram_gb = 0.0
    gpu_name = "GPU not detected"
    if isinstance(devices, list) and devices:
        device = devices[0] if isinstance(devices[0], dict) else {}
        vram_gb = _gb(device.get("vram_total"))
        gpu_name = str(device.get("name") or gpu_name)
    return vram_gb, ram_gb, gpu_name


def auto_profile(system_stats: dict | None) -> H3PerformanceProfile:
    vram_gb, ram_gb, _ = hardware_info(system_stats)
    # H3 is a very large model. Favor a conservative profile when hardware
    # information is unavailable or when either VRAM or system RAM is tight.
    if vram_gb <= 0 or vram_gb <= 8.5 or (ram_gb and ram_gb <= 20):
        return LOW_VRAM_PROFILE
    if vram_gb <= 12.5 or (ram_gb and ram_gb <= 32):
        return BALANCED_PROFILE
    return NATIVE_PROFILE


def custom_profile(settings) -> H3PerformanceProfile:
    megapixels = min(0.98, max(0.20, float(getattr(settings, "h3_megapixels", 0.40))))
    steps = min(40, max(4, int(getattr(settings, "h3_steps", 12))))
    max_refs = min(9, max(1, int(getattr(settings, "h3_max_references", 3))))
    ref_size = str(getattr(settings, "h3_ref_image_size", "match"))
    if ref_size not in {"match", "max"}:
        ref_size = "match"
    return H3PerformanceProfile(CUSTOM_PRESET, megapixels, steps, max_refs, ref_size, "Custom H3 settings.")


def resolve_profile(settings, system_stats: dict | None = None) -> H3PerformanceProfile:
    name = str(getattr(settings, "h3_performance_preset", AUTO_PRESET) or AUTO_PRESET)
    if name == AUTO_PRESET:
        detected = auto_profile(system_stats)
        return H3PerformanceProfile(
            AUTO_PRESET,
            detected.megapixels,
            detected.steps,
            detected.max_references,
            detected.ref_image_size,
            f"Auto selected {detected.name}.",
        )
    if name in STATIC_PRESETS:
        return STATIC_PRESETS[name]
    return custom_profile(settings)


def hardware_summary(system_stats: dict | None) -> str:
    vram_gb, ram_gb, gpu_name = hardware_info(system_stats)
    parts = [gpu_name]
    if vram_gb:
        parts.append(f"{vram_gb:.1f} GB VRAM")
    if ram_gb:
        parts.append(f"{ram_gb:.1f} GB RAM")
    return " • ".join(parts)
