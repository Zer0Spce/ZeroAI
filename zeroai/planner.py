from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

import requests

from .models import AppSettings, Scene


STYLE_GUIDANCE = {
    "UGC / TikTok": "authentic creator-style vertical video, natural handheld movement, direct eye contact, energetic but believable delivery",
    "Vlog": "casual vlog delivery, natural gestures, environmental movement, conversational camera presence",
    "Cinematic": "cinematic lighting and camera language, polished composition, deliberate motion, premium visual storytelling",
    "Commercial": "clean commercial framing, confident delivery, product-ad pacing, polished lighting and controlled camera movement",
    "Storytime": "intimate storytime delivery, expressive face and hands, escalating emotion, direct-to-camera pacing",
    "News Presenter": "clear presenter delivery, composed posture, concise pacing, broadcast-inspired framing without fake network branding",
}


@dataclass
class PlanResult:
    scenes: list[Scene]
    source: str


def _scene_count(duration: int) -> int:
    return max(1, math.ceil(duration / 12))


def _durations(total: int, count: int) -> list[int]:
    base = total // count
    remainder = total % count
    durations = [base + (1 if i < remainder else 0) for i in range(count)]
    return [max(4, min(15, d)) for d in durations]


def _reference_prefix(reference_count: int) -> str:
    if reference_count <= 0:
        return ""
    tags = ", ".join(f"<Picture {i}>" for i in range(1, reference_count + 1))
    return f"Identity references: {tags}. Keep the exact same person and facial identity throughout. "


def template_plan(direction: str, duration: int, style: str, aspect_ratio: str, reference_count: int) -> list[Scene]:
    count = _scene_count(duration)
    scene_durations = _durations(duration, count)
    if count == 1:
        beats = ["Hook + core message + clean finish"]
    else:
        beats = ["Immediate scroll-stopping hook"]
        middle = max(0, count - 2)
        beats.extend([f"Develop the topic — beat {i + 1}" for i in range(middle)])
        beats.append("Payoff, takeaway, and natural closing line")

    guidance = STYLE_GUIDANCE.get(style, STYLE_GUIDANCE["UGC / TikTok"])
    ref = _reference_prefix(reference_count)
    scenes: list[Scene] = []
    for i, seconds in enumerate(scene_durations):
        beat = beats[i]
        prompt = (
            f"{ref}{guidance}. {aspect_ratio} social video. Scene {i + 1} of {count}, about {seconds} seconds. "
            f"Creative direction: {direction.strip()}. This scene's purpose: {beat}. "
            "The influencer speaks naturally and clearly about the requested topic, using concise conversational dialogue that fits the time. "
            "Natural lip sync, believable facial motion, realistic hands, stable identity, no sudden wardrobe or face changes. "
            "Do not add logos, watermarks, captions, UI overlays, or on-screen text unless the direction explicitly asks for them."
        )
        scenes.append(Scene(index=i + 1, duration=seconds, beat=beat, prompt=prompt))
    return scenes


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        first, last = text.find("{"), text.rfind("}")
        if first >= 0 and last > first:
            text = text[first:last + 1]
    return json.loads(text)


def ollama_plan(direction: str, duration: int, style: str, aspect_ratio: str, reference_count: int, settings: AppSettings) -> list[Scene]:
    count = _scene_count(duration)
    durations = _durations(duration, count)
    schema_hint = {"scenes": [{"beat": "short purpose", "dialogue": "exact natural spoken line", "visual": "camera/action direction"}]}
    prompt = f"""
You are the scene planner for a Windows app named ZeroAI. Create exactly {count} short scenes for an AI influencer video.
Total target duration: {duration} seconds. Per-scene seconds: {durations}.
Style: {style}. Aspect ratio: {aspect_ratio}.
User direction: {direction}

Return ONLY valid JSON shaped like: {json.dumps(schema_hint)}
Rules:
- exactly {count} scenes
- dialogue must sound human, not corporate
- scene 1 needs a strong hook in the first sentence
- final scene needs a satisfying payoff/close, not a generic spammy CTA
- dialogue length must fit each scene's seconds
- visuals must be filmable by one consistent influencer
""".strip()
    response = requests.post(
        settings.ollama_url.rstrip("/") + "/api/generate",
        json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"},
        timeout=120,
    )
    response.raise_for_status()
    payload = _extract_json(response.json().get("response", "{}"))
    raw_scenes = payload.get("scenes", [])
    if len(raw_scenes) != count:
        raise ValueError("Planner returned the wrong number of scenes")

    ref = _reference_prefix(reference_count)
    guidance = STYLE_GUIDANCE.get(style, STYLE_GUIDANCE["UGC / TikTok"])
    scenes: list[Scene] = []
    for i, (seconds, item) in enumerate(zip(durations, raw_scenes)):
        beat = str(item.get("beat", f"Scene {i + 1}"))
        dialogue = str(item.get("dialogue", "")).strip()
        visual = str(item.get("visual", "")).strip()
        h3_prompt = (
            f"{ref}{guidance}. {aspect_ratio} social video. Scene {i + 1} of {count}, about {seconds} seconds. "
            f"Purpose: {beat}. Camera/action: {visual}. The influencer says exactly: \"{dialogue}\". "
            "Natural synchronized speech and lip movement, consistent face and body, realistic gestures, stable wardrobe and lighting continuity. "
            "No logos, watermarks, captions, or UI overlays unless explicitly requested."
        )
        scenes.append(Scene(index=i + 1, duration=seconds, beat=beat, prompt=h3_prompt))
    return scenes


def create_plan(direction: str, duration: int, style: str, aspect_ratio: str, reference_count: int, settings: AppSettings) -> PlanResult:
    if settings.planner_mode.lower().startswith("ollama"):
        try:
            return PlanResult(ollama_plan(direction, duration, style, aspect_ratio, reference_count, settings), "Ollama")
        except Exception:
            return PlanResult(template_plan(direction, duration, style, aspect_ratio, reference_count), "Template fallback")
    return PlanResult(template_plan(direction, duration, style, aspect_ratio, reference_count), "Template")
