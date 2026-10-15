from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QProgressBar, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .comfy import ComfyClient, ComfyError, load_workflow, prepare_workflow
from .models import AppSettings, Project
from .planner import create_plan
from .render import stitch_videos
from .storage import load_project, load_settings, save_project, save_settings


APP_QSS = """
QWidget { background: #0b0d12; color: #eef1f7; font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow { background: #0b0d12; }
QFrame#TopBar { background: #10131a; border-bottom: 1px solid #202532; }
QLabel#Brand { font-size: 18pt; font-weight: 800; }
QLabel#Muted { color: #8b93a7; }
QLabel#Chip { background: #171c26; color: #b9c1d3; border: 1px solid #293043; border-radius: 10px; padding: 3px 9px; }
QGroupBox { border: 1px solid #202532; border-radius: 12px; margin-top: 12px; padding: 12px; font-weight: 700; background: #10131a; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #dfe5f2; }
QLineEdit, QTextEdit, QComboBox, QSpinBox, QListWidget, QTableWidget { background: #0d1016; border: 1px solid #272d3b; border-radius: 8px; padding: 7px; selection-background-color: #5f7cff; }
QTextEdit:focus, QLineEdit:focus, QComboBox:focus, QListWidget:focus { border: 1px solid #6f86ff; }
QPushButton, QToolButton { background: #171c26; border: 1px solid #293043; border-radius: 8px; padding: 8px 12px; font-weight: 600; }
QPushButton:hover, QToolButton:hover { background: #202738; border-color: #3b4762; }
QPushButton:pressed { background: #111620; }
QPushButton#Primary { background: #6c7cff; border: 1px solid #8290ff; color: white; font-weight: 800; padding: 11px 16px; }
QPushButton#Primary:hover { background: #7887ff; }
QPushButton#Danger { color: #ff9da3; }
QHeaderView::section { background: #141923; color: #adb6ca; border: 0; border-bottom: 1px solid #252b38; padding: 8px; font-weight: 700; }
QTableWidget { gridline-color: #1d2230; }
QProgressBar { background: #11151d; border: 1px solid #242a37; border-radius: 7px; height: 12px; text-align: center; }
QProgressBar::chunk { background: #6c7cff; border-radius: 6px; }
QStatusBar { background: #0d1016; color: #8b93a7; }
"""


class ReferenceList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)
        self.setMinimumHeight(180)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.files_dropped.emit(paths)
        event.acceptProposedAction()


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("ZeroAI Settings")
        self.resize(650, 420)
        layout = QVBoxLayout(self)

        engine = QGroupBox("MiniMax H3 / ComfyUI")
        form = QGridLayout(engine)
        self.comfy_url = QLineEdit(settings.comfy_url)
        self.workflow = QLineEdit(settings.workflow_path)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.pick_workflow)
        form.addWidget(QLabel("ComfyUI URL"), 0, 0)
        form.addWidget(self.comfy_url, 0, 1, 1, 2)
        form.addWidget(QLabel("API workflow JSON"), 1, 0)
        form.addWidget(self.workflow, 1, 1)
        form.addWidget(browse, 1, 2)
        layout.addWidget(engine)

        planner = QGroupBox("Automatic Scene Planner")
        pform = QGridLayout(planner)
        self.planner_mode = QComboBox()
        self.planner_mode.addItems(["Template", "Ollama (local)"])
        self.planner_mode.setCurrentText(settings.planner_mode)
        self.ollama_url = QLineEdit(settings.ollama_url)
        self.ollama_model = QLineEdit(settings.ollama_model)
        pform.addWidget(QLabel("Planner"), 0, 0)
        pform.addWidget(self.planner_mode, 0, 1)
        pform.addWidget(QLabel("Ollama URL"), 1, 0)
        pform.addWidget(self.ollama_url, 1, 1)
        pform.addWidget(QLabel("Ollama model"), 2, 0)
        pform.addWidget(self.ollama_model, 2, 1)
        layout.addWidget(planner)

        output = QGroupBox("Output")
        oform = QGridLayout(output)
        self.output_root = QLineEdit(settings.output_root)
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self.pick_output)
        oform.addWidget(QLabel("Project folder"), 0, 0)
        oform.addWidget(self.output_root, 0, 1)
        oform.addWidget(out_browse, 0, 2)
        layout.addWidget(output)

        buttons = QHBoxLayout()
        test = QPushButton("Test ComfyUI")
        test.clicked.connect(self.test_comfy)
        buttons.addWidget(test)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        save = QPushButton("Save")
        save.setObjectName("Primary")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def pick_workflow(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select ComfyUI API workflow", "", "JSON (*.json)")
        if path:
            self.workflow.setText(path)

    def pick_output(self):
        path = QFileDialog.getExistingDirectory(self, "Choose ZeroAI project folder", self.output_root.text())
        if path:
            self.output_root.setText(path)

    def test_comfy(self):
        ok = ComfyClient(self.comfy_url.text().strip()).check()
        QMessageBox.information(self, "ComfyUI", "Connected successfully." if ok else "Could not connect to ComfyUI.")

    def apply(self):
        self.settings.comfy_url = self.comfy_url.text().strip()
        self.settings.workflow_path = self.workflow.text().strip()
        self.settings.planner_mode = self.planner_mode.currentText()
        self.settings.ollama_url = self.ollama_url.text().strip()
        self.settings.ollama_model = self.ollama_model.text().strip()
        self.settings.output_root = self.output_root.text().strip()
        save_settings(self.settings)


class GenerationThread(QThread):
    log = Signal(str)
    scene_status = Signal(int, str, str)
    progress = Signal(int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, project: Project, settings: AppSettings):
        super().__init__()
        self.project = project
        self.settings = settings
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    @staticmethod
    def resolution(aspect: str) -> tuple[int, int]:
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
            workflow_template = load_workflow(self.settings.workflow_path)

            self.log.emit("Uploading influencer reference images…")
            uploaded = []
            for path in self.project.references[:9]:
                if self.cancelled:
                    raise ComfyError("Generation cancelled")
                uploaded.append(client.upload_image(path))
            self.log.emit(f"Uploaded {len(uploaded)} reference image(s).")

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in self.project.name).strip() or "ZeroAI_Project"
            project_dir = Path(self.settings.output_root) / safe_name / stamp
            clips_dir = project_dir / "scenes"
            clips_dir.mkdir(parents=True, exist_ok=True)
            width, height = self.resolution(self.project.aspect_ratio)
            clip_paths = []

            for pos, scene in enumerate(self.project.scenes):
                if self.cancelled:
                    raise ComfyError("Generation cancelled")
                self.scene_status.emit(scene.index, "Generating", "")
                self.log.emit(f"Scene {scene.index}/{len(self.project.scenes)} — {scene.beat}")
                workflow = prepare_workflow(
                    workflow_template,
                    prompt=scene.prompt,
                    width=width,
                    height=height,
                    duration=scene.duration,
                    references=uploaded,
                )
                prompt_id = client.queue(workflow)
                record = client.wait(prompt_id, cancelled=lambda: self.cancelled)
                clip_path = clips_dir / f"scene_{scene.index:02d}.mp4"
                client.download_video(record, clip_path)
                scene.output_path = str(clip_path)
                scene.status = "Done"
                clip_paths.append(clip_path)
                self.scene_status.emit(scene.index, "Done", str(clip_path))
                self.progress.emit(int(((pos + 1) / len(self.project.scenes)) * 90))

            final = project_dir / f"{safe_name}.mp4"
            self.log.emit("Stitching scenes into the final video…")
            stitch_videos(clip_paths, final)
            self.project.final_output = str(final)
            save_project(self.project, project_dir / f"{safe_name}.zeroai.json")
            self.progress.emit(100)
            self.finished_ok.emit(str(final))
        except Exception as exc:
            self.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=3)}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.project = Project()
        self.project_path: str | None = None
        self.worker: GenerationThread | None = None
        self.setWindowTitle("ZeroAI — AI Influencer Video Studio")
        self.resize(1500, 900)
        self.setMinimumSize(1180, 720)
        self.setStyleSheet(APP_QSS)
        self.build_ui()
        self.build_menu()
        self.refresh_engine_status()

    def build_menu(self):
        menu = self.menuBar().addMenu("File")
        new_action = QAction("New Project", self)
        open_action = QAction("Open Project…", self)
        save_action = QAction("Save Project", self)
        save_as_action = QAction("Save Project As…", self)
        new_action.triggered.connect(self.new_project)
        open_action.triggered.connect(self.open_project)
        save_action.triggered.connect(self.save_project)
        save_as_action.triggered.connect(lambda: self.save_project(save_as=True))
        menu.addActions([new_action, open_action, save_action, save_as_action])

    def build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QFrame(objectName="TopBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(18, 10, 18, 10)
        brand = QLabel("ZeroAI", objectName="Brand")
        subtitle = QLabel("AI Influencer Video Studio", objectName="Muted")
        self.engine_chip = QLabel("ComfyUI: checking…", objectName="Chip")
        settings_btn = QToolButton()
        settings_btn.setText("⚙  Settings")
        settings_btn.clicked.connect(self.open_settings)
        top_layout.addWidget(brand)
        top_layout.addWidget(subtitle)
        top_layout.addStretch()
        top_layout.addWidget(self.engine_chip)
        top_layout.addWidget(settings_btn)
        outer.addWidget(top)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.build_left())
        splitter.addWidget(self.build_center())
        splitter.addWidget(self.build_right())
        splitter.setSizes([300, 690, 430])
        outer.addWidget(splitter, 1)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def build_left(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 7, 14)
        refs = QGroupBox("AI Influencer")
        rlayout = QVBoxLayout(refs)
        hint = QLabel("Drop 1–9 reference images. H3 can use them to keep identity consistent.")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        self.refs = ReferenceList()
        self.refs.files_dropped.connect(self.add_reference_paths)
        ref_buttons = QHBoxLayout()
        add = QPushButton("+ Add Images")
        remove = QPushButton("Remove")
        add.clicked.connect(self.pick_references)
        remove.clicked.connect(self.remove_reference)
        ref_buttons.addWidget(add)
        ref_buttons.addWidget(remove)
        rlayout.addWidget(hint)
        rlayout.addWidget(self.refs)
        rlayout.addLayout(ref_buttons)
        layout.addWidget(refs)

        tips = QGroupBox("Reference Tips")
        tlayout = QVBoxLayout(tips)
        text = QLabel("• Use clear, sharp photos\n• Mix close-up + upper body\n• Keep the same character\n• Avoid heavy filters\n• Up to 9 images")
        text.setObjectName("Muted")
        tlayout.addWidget(text)
        layout.addWidget(tips)
        layout.addStretch()
        return panel

    def build_center(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(7, 14, 7, 14)

        direction_group = QGroupBox("What should your influencer make?")
        dlayout = QVBoxLayout(direction_group)
        self.direction = QTextEdit()
        self.direction.setPlaceholderText("Example: Explain why people dream while sleeping. Make the first 3 seconds a strong hook, casual TikTok delivery, curious and slightly mysterious.")
        self.direction.setMinimumHeight(125)
        dlayout.addWidget(self.direction)
        layout.addWidget(direction_group)

        options = QGroupBox("Video Setup")
        grid = QGridLayout(options)
        self.name_edit = QLineEdit("Untitled Project")
        self.duration = QComboBox()
        self.duration.addItems(["15", "30", "45", "60", "90", "120"])
        self.duration.setCurrentText("30")
        self.aspect = QComboBox()
        self.aspect.addItems(["9:16", "16:9", "1:1"])
        self.style = QComboBox()
        self.style.addItems(["UGC / TikTok", "Vlog", "Cinematic", "Commercial", "Storytime", "News Presenter"])
        grid.addWidget(QLabel("Project"), 0, 0)
        grid.addWidget(self.name_edit, 0, 1, 1, 3)
        grid.addWidget(QLabel("Duration"), 1, 0)
        grid.addWidget(self.duration, 1, 1)
        grid.addWidget(QLabel("Format"), 1, 2)
        grid.addWidget(self.aspect, 1, 3)
        grid.addWidget(QLabel("Style"), 2, 0)
        grid.addWidget(self.style, 2, 1, 1, 3)
        layout.addWidget(options)

        action_row = QHBoxLayout()
        plan = QPushButton("✨ Plan Scenes")
        plan.clicked.connect(self.plan_scenes)
        self.generate_btn = QPushButton("▶  Generate Video")
        self.generate_btn.setObjectName("Primary")
        self.generate_btn.clicked.connect(self.generate_video)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_generation)
        action_row.addWidget(plan)
        action_row.addStretch()
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.generate_btn)
        layout.addLayout(action_row)

        timeline = QGroupBox("Scene Timeline")
        tlayout = QVBoxLayout(timeline)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Seconds", "Scene beat", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_scene_prompt)
        tlayout.addWidget(self.table)
        layout.addWidget(timeline, 1)
        return panel

    def build_right(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(7, 14, 14, 14)

        preview = QGroupBox("Preview")
        playout = QVBoxLayout(preview)
        self.video = QVideoWidget()
        self.video.setMinimumHeight(300)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        preview_buttons = QHBoxLayout()
        play = QPushButton("Play / Pause")
        play.clicked.connect(self.toggle_play)
        open_out = QPushButton("Open Output")
        open_out.clicked.connect(self.open_output)
        preview_buttons.addWidget(play)
        preview_buttons.addWidget(open_out)
        playout.addWidget(self.video)
        playout.addLayout(preview_buttons)
        layout.addWidget(preview)

        run = QGroupBox("Generation")
        rlayout = QVBoxLayout(run)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(170)
        rlayout.addWidget(self.progress)
        rlayout.addWidget(self.log)
        layout.addWidget(run, 1)
        return panel

    def sync_project_from_ui(self):
        self.project.name = self.name_edit.text().strip() or "Untitled Project"
        self.project.direction = self.direction.toPlainText().strip()
        self.project.duration = int(self.duration.currentText())
        self.project.aspect_ratio = self.aspect.currentText()
        self.project.style = self.style.currentText()
        self.project.references = [self.refs.item(i).data(Qt.UserRole) for i in range(self.refs.count())]

    def refresh_refs(self):
        self.refs.clear()
        for path in self.project.references:
            item = QListWidgetItem(Path(path).name)
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.refs.addItem(item)

    def add_reference_paths(self, paths: list[str]):
        valid_ext = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        existing = {self.refs.item(i).data(Qt.UserRole) for i in range(self.refs.count())}
        for path in paths:
            if len(existing) >= 9:
                break
            if Path(path).suffix.lower() in valid_ext and path not in existing:
                item = QListWidgetItem(Path(path).name)
                item.setToolTip(path)
                item.setData(Qt.UserRole, path)
                self.refs.addItem(item)
                existing.add(path)

    def pick_references(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose influencer references", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        self.add_reference_paths(paths)

    def remove_reference(self):
        for item in self.refs.selectedItems():
            self.refs.takeItem(self.refs.row(item))

    def plan_scenes(self):
        self.sync_project_from_ui()
        if not self.project.direction:
            QMessageBox.warning(self, "Direction needed", "Tell ZeroAI what the influencer should talk about or do.")
            return
        result = create_plan(
            self.project.direction, self.project.duration, self.project.style,
            self.project.aspect_ratio, len(self.project.references), self.settings,
        )
        self.project.scenes = result.scenes
        self.populate_scenes()
        self.append_log(f"Planned {len(result.scenes)} scene(s) using {result.source}.")

    def populate_scenes(self):
        self.table.setRowCount(len(self.project.scenes))
        for row, scene in enumerate(self.project.scenes):
            self.table.setItem(row, 0, QTableWidgetItem(str(scene.index)))
            self.table.setItem(row, 1, QTableWidgetItem(str(scene.duration)))
            self.table.setItem(row, 2, QTableWidgetItem(scene.beat))
            self.table.setItem(row, 3, QTableWidgetItem(scene.status))

    def edit_scene_prompt(self, index):
        row = index.row()
        if not (0 <= row < len(self.project.scenes)):
            return
        scene = self.project.scenes[row]
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Scene {scene.index} Prompt")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        text = QTextEdit(scene.prompt)
        layout.addWidget(text)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        save = QPushButton("Save Prompt")
        save.setObjectName("Primary")
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        if dialog.exec() == QDialog.Accepted:
            scene.prompt = text.toPlainText().strip()

    def generate_video(self):
        self.sync_project_from_ui()
        if not self.project.direction:
            QMessageBox.warning(self, "Direction needed", "Enter a topic or direction first.")
            return
        if not self.project.scenes:
            self.plan_scenes()
        if not self.project.scenes:
            return
        if not self.settings.workflow_path:
            QMessageBox.warning(self, "Workflow needed", "Open Settings and select your exported ComfyUI H3 API workflow JSON first.")
            return
        self.set_running(True)
        self.progress.setValue(0)
        self.worker = GenerationThread(self.project, self.settings)
        self.worker.log.connect(self.append_log)
        self.worker.scene_status.connect(self.on_scene_status)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished_ok.connect(self.on_generation_done)
        self.worker.failed.connect(self.on_generation_failed)
        self.worker.start()

    def cancel_generation(self):
        if self.worker:
            self.worker.cancel()
            self.append_log("Cancelling after the current network operation…")

    def on_scene_status(self, scene_index: int, status: str, output: str):
        for row, scene in enumerate(self.project.scenes):
            if scene.index == scene_index:
                scene.status = status
                if output:
                    scene.output_path = output
                self.table.setItem(row, 3, QTableWidgetItem(status))
                break

    def on_generation_done(self, path: str):
        self.project.final_output = path
        self.set_running(False)
        self.append_log(f"Finished: {path}")
        self.statusBar().showMessage("Video finished")
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def on_generation_failed(self, message: str):
        self.set_running(False)
        self.append_log("ERROR: " + message)
        QMessageBox.critical(self, "Generation failed", message.split("\n\n")[0])

    def set_running(self, running: bool):
        self.generate_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)

    def append_log(self, message: str):
        self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def refresh_engine_status(self):
        ok = ComfyClient(self.settings.comfy_url).check()
        self.engine_chip.setText("ComfyUI: Online" if ok else "ComfyUI: Offline")

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            dialog.apply()
            self.refresh_engine_status()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def open_output(self):
        path = self.project.final_output
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
        else:
            QMessageBox.information(self, "No output yet", "Generate a video first.")

    def save_project(self, save_as=False):
        self.sync_project_from_ui()
        path = self.project_path
        if save_as or not path:
            suggested = str(Path(self.settings.output_root) / f"{self.project.name}.zeroai.json")
            path, _ = QFileDialog.getSaveFileName(self, "Save ZeroAI Project", suggested, "ZeroAI Project (*.zeroai.json)")
        if path:
            self.project_path = str(save_project(self.project, path))
            self.statusBar().showMessage(f"Saved {self.project_path}")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open ZeroAI Project", self.settings.output_root, "ZeroAI Project (*.zeroai.json)")
        if not path:
            return
        self.project = load_project(path)
        self.project_path = path
        self.name_edit.setText(self.project.name)
        self.direction.setPlainText(self.project.direction)
        self.duration.setCurrentText(str(self.project.duration))
        self.aspect.setCurrentText(self.project.aspect_ratio)
        self.style.setCurrentText(self.project.style)
        self.refresh_refs()
        self.populate_scenes()
        if self.project.final_output and Path(self.project.final_output).exists():
            self.player.setSource(QUrl.fromLocalFile(self.project.final_output))

    def new_project(self):
        self.project = Project()
        self.project_path = None
        self.name_edit.setText(self.project.name)
        self.direction.clear()
        self.duration.setCurrentText("30")
        self.aspect.setCurrentText("9:16")
        self.style.setCurrentText("UGC / TikTok")
        self.refs.clear()
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.log.clear()
        self.player.setSource(QUrl())


def run_app() -> int:
    if sys.platform != "win32":
        print("ZeroAI is Windows-only.")
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName("ZeroAI")
    app.setOrganizationName("Zer0Spce")
    window = MainWindow()
    window.show()
    return app.exec()
