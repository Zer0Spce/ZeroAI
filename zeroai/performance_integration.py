from __future__ import annotations

import time
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
)

from .builtin_workflows import BUILTIN_H3_URI, adapt_h3_canvas
from .comfy import ComfyClient, ComfyError, load_workflow, prepare_workflow
from .performance import (
    AUTO_PRESET,
    CUSTOM_PRESET,
    PRESET_NAMES,
    RESOLUTION_OPTIONS,
    STATIC_PRESETS,
    auto_profile,
    custom_profile,
    hardware_summary,
    resolve_profile,
)
from .render import stitch_videos
from .storage import save_project, save_settings


def _workflow_is_h3(template: dict) -> bool:
    return any(
        isinstance(node, dict) and node.get("class_type") == "MiniMaxH3ReferenceToVideo"
        for node in template.values()
    )


def _format_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def install_performance_integration(ui_module) -> None:
    """Add render-performance controls and real ComfyUI sampler progress."""
    BaseSettingsDialog = ui_module.SettingsDialog
    BaseGenerationThread = ui_module.GenerationThread

    class PerformanceSettingsDialog(BaseSettingsDialog):
        def __init__(self, settings, parent=None):
            super().__init__(settings, parent)
            self.resize(820, 820)
            self._system_stats: dict = {}

            group = QGroupBox("H3 Performance")
            grid = QGridLayout(group)

            self.perf_preset = QComboBox()
            self.perf_preset.addItems(PRESET_NAMES)
            preset = getattr(settings, "h3_performance_preset", AUTO_PRESET)
            self.perf_preset.setCurrentText(preset if preset in PRESET_NAMES else AUTO_PRESET)

            self.perf_resolution = QComboBox()
            for label, value in RESOLUTION_OPTIONS:
                self.perf_resolution.addItem(label, value)

            self.perf_steps = QSpinBox()
            self.perf_steps.setRange(4, 40)
            self.perf_steps.setSuffix(" steps")
            self.perf_steps.setValue(int(getattr(settings, "h3_steps", 12)))

            self.perf_refs = QSpinBox()
            self.perf_refs.setRange(1, 9)
            self.perf_refs.setSuffix(" refs")
            self.perf_refs.setValue(int(getattr(settings, "h3_max_references", 3)))

            self.perf_ref_size = QComboBox()
            self.perf_ref_size.addItem("match — faster / less VRAM", "match")
            self.perf_ref_size.addItem("max — stronger identity / slower", "max")
            saved_ref_size = str(getattr(settings, "h3_ref_image_size", "match"))
            self.perf_ref_size.setCurrentIndex(1 if saved_ref_size == "max" else 0)

            saved_mp = float(getattr(settings, "h3_megapixels", 0.40))
            self._set_resolution(saved_mp)

            refresh_gpu = QPushButton("Refresh GPU")
            refresh_gpu.clicked.connect(self.refresh_hardware)
            self.hardware_label = QLabel("Detecting ComfyUI hardware…")
            self.hardware_label.setObjectName("Muted")
            self.hardware_label.setWordWrap(True)

            self.performance_note = QLabel()
            self.performance_note.setObjectName("Muted")
            self.performance_note.setWordWrap(True)

            grid.addWidget(QLabel("Preset"), 0, 0)
            grid.addWidget(self.perf_preset, 0, 1, 1, 2)
            grid.addWidget(refresh_gpu, 0, 3)
            grid.addWidget(QLabel("Resolution"), 1, 0)
            grid.addWidget(self.perf_resolution, 1, 1)
            grid.addWidget(QLabel("Sampling"), 1, 2)
            grid.addWidget(self.perf_steps, 1, 3)
            grid.addWidget(QLabel("Reference limit"), 2, 0)
            grid.addWidget(self.perf_refs, 2, 1)
            grid.addWidget(QLabel("Reference size"), 2, 2)
            grid.addWidget(self.perf_ref_size, 2, 3)
            grid.addWidget(self.hardware_label, 3, 0, 1, 4)
            grid.addWidget(self.performance_note, 4, 0, 1, 4)

            root_layout = self.layout()
            insert_at = max(0, root_layout.count() - 1)
            root_layout.insertWidget(insert_at, group)

            self.perf_preset.currentTextChanged.connect(self.on_preset_changed)
            self.perf_resolution.currentIndexChanged.connect(self._custom_control_changed)
            self.perf_steps.valueChanged.connect(self._custom_control_changed)
            self.perf_refs.valueChanged.connect(self._custom_control_changed)
            self.perf_ref_size.currentIndexChanged.connect(self._custom_control_changed)

            self.refresh_hardware()
            self.on_preset_changed(self.perf_preset.currentText(), mark_custom=False)

        def _set_resolution(self, value: float):
            best = min(
                range(self.perf_resolution.count()),
                key=lambda i: abs(float(self.perf_resolution.itemData(i)) - float(value)),
            )
            self.perf_resolution.setCurrentIndex(best)

        def _set_controls_from_profile(self, profile):
            widgets = [self.perf_resolution, self.perf_steps, self.perf_refs, self.perf_ref_size]
            for widget in widgets:
                widget.blockSignals(True)
            try:
                self._set_resolution(profile.megapixels)
                self.perf_steps.setValue(profile.steps)
                self.perf_refs.setValue(profile.max_references)
                self.perf_ref_size.setCurrentIndex(1 if profile.ref_image_size == "max" else 0)
            finally:
                for widget in widgets:
                    widget.blockSignals(False)
            self.performance_note.setText(
                f"Effective H3 render: {profile.megapixels:.2f} MP • {profile.steps} steps • "
                f"up to {profile.max_references} reference image(s) • ref size {profile.ref_image_size}. "
                f"{profile.note}"
            )

        def refresh_hardware(self):
            try:
                self._system_stats = ComfyClient(self.comfy_url.text().strip()).system_stats()
                self.hardware_label.setText("Detected: " + hardware_summary(self._system_stats))
            except Exception:
                self._system_stats = {}
                self.hardware_label.setText("ComfyUI hardware detection unavailable. Auto uses the safe low-VRAM preset.")
            if self.perf_preset.currentText() == AUTO_PRESET:
                self._set_controls_from_profile(auto_profile(self._system_stats))

        def on_preset_changed(self, name: str, mark_custom: bool = True):
            if name == AUTO_PRESET:
                profile = auto_profile(self._system_stats)
            elif name in STATIC_PRESETS:
                profile = STATIC_PRESETS[name]
            elif name == CUSTOM_PRESET:
                profile = custom_profile(self.settings)
                # Preserve what is already visible when the user explicitly
                # switched to Custom instead of snapping back to saved values.
                if mark_custom:
                    self.performance_note.setText(
                        "Custom mode: choose resolution, steps, reference limit, and reference image size below."
                    )
                    return
            else:
                profile = auto_profile(self._system_stats)
            self._set_controls_from_profile(profile)

        def _custom_control_changed(self, *_):
            # Editing a performance knob turns a named preset into Custom. Block
            # the signal so current values are not reset by on_preset_changed.
            if self.perf_preset.currentText() != CUSTOM_PRESET:
                self.perf_preset.blockSignals(True)
                self.perf_preset.setCurrentText(CUSTOM_PRESET)
                self.perf_preset.blockSignals(False)
            self.performance_note.setText(
                "Custom mode. For base Ref2VA, 20 steps is the official quality target; fewer steps trade quality for speed."
            )

        def apply(self):
            super().apply()
            self.settings.h3_performance_preset = self.perf_preset.currentText()
            self.settings.h3_megapixels = float(self.perf_resolution.currentData())
            self.settings.h3_steps = int(self.perf_steps.value())
            self.settings.h3_max_references = int(self.perf_refs.value())
            self.settings.h3_ref_image_size = str(self.perf_ref_size.currentData())
            save_settings(self.settings)

    class PerformanceGenerationThread(BaseGenerationThread):
        @staticmethod
        def _base_resolution(aspect: str) -> tuple[int, int]:
            return {
                "9:16": (768, 1360),
                "16:9": (1360, 768),
                "1:1": (1024, 1024),
            }.get(aspect, (768, 1360))

        def run(self):
            try:
                client = ComfyClient(self.settings.comfy_url, self.settings.poll_interval_seconds)
                if not client.check():
                    raise ComfyError("ComfyUI is offline. Start ComfyUI and check Settings > ComfyUI URL.")

                try:
                    stats = client.system_stats()
                except Exception:
                    stats = {}

                workflow_template = load_workflow(self.settings.workflow_path)
                is_h3 = _workflow_is_h3(workflow_template)
                profile = resolve_profile(self.settings, stats) if is_h3 else None

                if profile:
                    self.log.emit(
                        f"Performance: {profile.name} — {profile.megapixels:.2f} MP, "
                        f"{profile.steps} steps, max {profile.max_references} refs, ref size {profile.ref_image_size}."
                    )
                    summary = hardware_summary(stats)
                    if summary and summary != "GPU not detected":
                        self.log.emit(f"Hardware: {summary}")

                max_refs = profile.max_references if profile else 9
                reference_paths = self.project.references[:max_refs]
                if profile and len(self.project.references) > max_refs:
                    self.log.emit(
                        f"Speed preset is using the first {max_refs} of {len(self.project.references)} references. "
                        "Increase Reference limit in Settings if you need all of them."
                    )

                self.log.emit("Uploading influencer reference images…")
                uploaded = []
                total_refs = max(1, len(reference_paths))
                for index, path in enumerate(reference_paths):
                    if self.cancelled:
                        raise ComfyError("Generation cancelled")
                    uploaded.append(client.upload_image(path))
                    self.progress.emit(min(5, int(((index + 1) / total_refs) * 5)))
                self.log.emit(f"Uploaded {len(uploaded)} reference image(s).")

                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in self.project.name).strip() or "ZeroAI_Project"
                project_dir = Path(self.settings.output_root) / safe_name / stamp
                clips_dir = project_dir / "scenes"
                clips_dir.mkdir(parents=True, exist_ok=True)
                width, height = self._base_resolution(self.project.aspect_ratio)
                if profile:
                    render_w, render_h = adapt_h3_canvas(width, height, profile.megapixels)
                    self.log.emit(f"H3 canvas: {render_w}×{render_h} ({profile.megapixels:.2f} MP target).")
                clip_paths = []

                scene_count = max(1, len(self.project.scenes))
                scene_total_weight = 88.0

                for pos, scene in enumerate(self.project.scenes):
                    if self.cancelled:
                        raise ComfyError("Generation cancelled")

                    scene_start = 5.0 + scene_total_weight * (pos / scene_count)
                    scene_span = scene_total_weight / scene_count

                    def update_scene(local_fraction: float, status_text: str):
                        local_fraction = max(0.0, min(1.0, local_fraction))
                        overall = int(scene_start + scene_span * local_fraction)
                        self.progress.emit(min(93, max(0, overall)))
                        self.scene_status.emit(scene.index, status_text, "")

                    update_scene(0.02, "Preparing")
                    self.log.emit(f"Scene {scene.index}/{scene_count} — {scene.beat}")
                    workflow = prepare_workflow(
                        workflow_template,
                        prompt=scene.prompt,
                        width=width,
                        height=height,
                        duration=scene.duration,
                        references=uploaded,
                        steps=profile.steps if profile else None,
                        h3_megapixels=profile.megapixels if profile else None,
                        ref_image_size=profile.ref_image_size if profile else "match",
                    )
                    prompt_id = client.queue(workflow)
                    update_scene(0.05, "Queued / loading")

                    sampling_started: list[float | None] = [None]
                    logged_milestones: set[int] = set()

                    def on_status(status: str):
                        if status == "complete":
                            update_scene(0.97, "Finalizing")
                            return
                        if status.startswith("executing:"):
                            node_id = status.split(":", 1)[1]
                            node = workflow.get(str(node_id), {})
                            class_type = node.get("class_type", "") if isinstance(node, dict) else ""
                            title = node.get("_meta", {}).get("title", "") if isinstance(node, dict) else ""
                            if class_type in {"UNETLoader", "CLIPLoader", "VAELoader"}:
                                update_scene(0.08, "Loading H3 model")
                            elif class_type == "MiniMaxH3ReferenceToVideo":
                                update_scene(0.12, "Encoding references")
                            elif class_type in {"VAEDecode", "VAEDecodeAudio"}:
                                update_scene(0.90, "Decoding video/audio")
                            elif class_type == "CreateVideo":
                                update_scene(0.94, "Muxing video/audio")
                            elif class_type == "SaveVideo":
                                update_scene(0.96, "Saving clip")
                            elif title:
                                update_scene(0.10, title)

                    def on_progress(value: int, maximum: int, _node: str | None):
                        if maximum <= 0:
                            return
                        now = time.monotonic()
                        if sampling_started[0] is None:
                            sampling_started[0] = now
                            self.log.emit(f"Scene {scene.index}: live sampler progress connected ({maximum} steps).")
                        fraction = max(0.0, min(1.0, value / maximum))
                        local = 0.15 + 0.72 * fraction
                        eta_text = ""
                        if fraction >= 0.05 and sampling_started[0] is not None:
                            elapsed = max(0.01, now - sampling_started[0])
                            remaining = elapsed * (1.0 - fraction) / fraction
                            eta_text = f" • ETA {_format_eta(remaining)}"
                        update_scene(local, f"Sampling {value}/{maximum} • {fraction * 100:.0f}%{eta_text}")

                        milestone = min(100, int(fraction * 100) // 25 * 25)
                        if milestone in {25, 50, 75, 100} and milestone not in logged_milestones:
                            logged_milestones.add(milestone)
                            self.log.emit(f"Scene {scene.index}: sampling {milestone}%")

                    record = client.wait(
                        prompt_id,
                        on_status=on_status,
                        on_progress=on_progress,
                        cancelled=lambda: self.cancelled,
                    )
                    update_scene(0.98, "Downloading clip")
                    clip_path = clips_dir / f"scene_{scene.index:02d}.mp4"
                    client.download_video(record, clip_path)
                    scene.output_path = str(clip_path)
                    scene.status = "Done"
                    clip_paths.append(clip_path)
                    self.scene_status.emit(scene.index, "Done", str(clip_path))
                    self.progress.emit(int(scene_start + scene_span))

                final = project_dir / f"{safe_name}.mp4"
                self.progress.emit(95)
                self.log.emit("Stitching scenes into the final video…")
                stitch_videos(clip_paths, final)
                self.progress.emit(99)
                self.project.final_output = str(final)
                save_project(self.project, project_dir / f"{safe_name}.zeroai.json")
                self.progress.emit(100)
                self.finished_ok.emit(str(final))
            except Exception as exc:
                self.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=3)}")

    ui_module.SettingsDialog = PerformanceSettingsDialog
    ui_module.GenerationThread = PerformanceGenerationThread
