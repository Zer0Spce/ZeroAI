from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTextEdit,
)

from .builtin_workflows import BUILTIN_H3_NAME, BUILTIN_H3_URI, local_workflow_dir, write_builtin_workflow_files
from .comfy import ComfyClient
from .h3_setup import (
    H3_MODEL_FILES,
    TOTAL_EXPECTED_BYTES,
    detect_comfyui_root,
    format_bytes,
    install_h3_models,
    missing_models,
    model_status,
    normalize_comfyui_root,
)
from .storage import save_settings


LEGACY_ZEROAI_WORKFLOW_NAMES = {
    "minimax_h3_ref2va_zeroai_1ref_api.json",
    "minimax_h3_ref2va_zeroai_9ref_api.json",
    "minimax_h3_ref2va_zeroai_api.json",
}


def _is_builtin_or_legacy(path: str) -> bool:
    if not path or path == BUILTIN_H3_URI:
        return True
    return Path(path).name.lower() in LEGACY_ZEROAI_WORKFLOW_NAMES


class H3DownloadThread(QThread):
    progress_changed = Signal(int, str)
    log_line = Signal(str)
    installed = Signal()
    failed = Signal(str)

    def __init__(self, comfy_root: str):
        super().__init__()
        self.comfy_root = comfy_root
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            install_h3_models(
                self.comfy_root,
                progress=lambda percent, text: self.progress_changed.emit(percent, text),
                log=self.log_line.emit,
                cancelled=lambda: self._cancelled,
            )
            self.installed.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


def install_h3_integration(ui_module) -> None:
    """Upgrade the v0.1 UI at runtime without duplicating the main window implementation."""
    try:
        write_builtin_workflow_files()
    except OSError:
        pass

    BaseSettingsDialog = ui_module.SettingsDialog
    BaseMainWindow = ui_module.MainWindow

    class EnhancedSettingsDialog(BaseSettingsDialog):
        def __init__(self, settings, parent=None):
            super().__init__(settings, parent)
            self.setWindowTitle("ZeroAI Settings — MiniMax H3")
            self.resize(760, 700)
            self.h3_worker: H3DownloadThread | None = None

            if _is_builtin_or_legacy(self.workflow.text().strip()):
                self.workflow.clear()
            self.workflow.setPlaceholderText("Built-in ZeroAI MiniMax H3 Ref2VA workflow (recommended)")

            group = QGroupBox("MiniMax H3 — One-Click Setup")
            grid = QGridLayout(group)

            self.comfy_path = QLineEdit(getattr(settings, "comfy_path", ""))
            self.comfy_path.setPlaceholderText(r"Example: C:\ComfyUI or ...\ComfyUI_windows_portable\ComfyUI")
            detect_btn = QPushButton("Detect")
            browse_btn = QPushButton("Browse…")
            detect_btn.clicked.connect(self.detect_comfyui)
            browse_btn.clicked.connect(self.browse_comfyui)

            grid.addWidget(QLabel("ComfyUI folder"), 0, 0)
            grid.addWidget(self.comfy_path, 0, 1)
            path_buttons = QHBoxLayout()
            path_buttons.addWidget(detect_btn)
            path_buttons.addWidget(browse_btn)
            grid.addLayout(path_buttons, 0, 2)

            workflow_label = QLabel(f"Workflow: {BUILTIN_H3_NAME}")
            workflow_label.setWordWrap(True)
            use_builtin = QPushButton("Use Built-in Workflow")
            use_builtin.clicked.connect(self.use_builtin_workflow)
            open_workflows = QPushButton("Open Built-in JSONs")
            open_workflows.clicked.connect(self.open_builtin_workflows)
            grid.addWidget(workflow_label, 1, 0, 1, 2)
            workflow_buttons = QHBoxLayout()
            workflow_buttons.addWidget(use_builtin)
            workflow_buttons.addWidget(open_workflows)
            grid.addLayout(workflow_buttons, 1, 2)

            self.h3_status = QLabel("Checking MiniMax H3 files…")
            self.h3_status.setWordWrap(True)
            self.h3_status.setObjectName("Muted")
            grid.addWidget(self.h3_status, 2, 0, 1, 3)

            self.h3_progress = QProgressBar()
            self.h3_progress.setRange(0, 100)
            self.h3_progress.setValue(0)
            grid.addWidget(self.h3_progress, 3, 0, 1, 3)

            self.h3_progress_text = QLabel("Downloads resume automatically if interrupted.")
            self.h3_progress_text.setWordWrap(True)
            self.h3_progress_text.setObjectName("Muted")
            grid.addWidget(self.h3_progress_text, 4, 0, 1, 3)

            self.h3_log = QTextEdit()
            self.h3_log.setReadOnly(True)
            self.h3_log.setMaximumHeight(105)
            grid.addWidget(self.h3_log, 5, 0, 1, 3)

            install_row = QHBoxLayout()
            self.install_h3_btn = QPushButton(f"Download / Repair H3 ({format_bytes(TOTAL_EXPECTED_BYTES)})")
            self.install_h3_btn.setObjectName("Primary")
            self.install_h3_btn.clicked.connect(self.install_h3)
            self.cancel_h3_btn = QPushButton("Cancel Download")
            self.cancel_h3_btn.setEnabled(False)
            self.cancel_h3_btn.clicked.connect(self.cancel_h3)
            check_btn = QPushButton("Check Again")
            check_btn.clicked.connect(self.refresh_h3_status)
            install_row.addWidget(check_btn)
            install_row.addStretch()
            install_row.addWidget(self.cancel_h3_btn)
            install_row.addWidget(self.install_h3_btn)
            grid.addLayout(install_row, 6, 0, 1, 3)

            note = QLabel(
                "Downloads the official Comfy-Org MiniMax H3 Ref2VA model, Qwen3-VL encoder, "
                "video VAE, and audio VAE directly into ComfyUI. Restart ComfyUI after installation."
            )
            note.setWordWrap(True)
            note.setObjectName("Muted")
            grid.addWidget(note, 7, 0, 1, 3)

            root_layout = self.layout()
            insert_at = max(0, root_layout.count() - 1)
            root_layout.insertWidget(insert_at, group)

            if not self.comfy_path.text().strip():
                self.detect_comfyui(quiet=True)
            self.refresh_h3_status()

        def use_builtin_workflow(self):
            self.workflow.clear()
            self.h3_log.append("Built-in adaptive Ref2VA workflow selected (1–9 references).")

        def open_builtin_workflows(self):
            try:
                write_builtin_workflow_files()
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(local_workflow_dir())))
            except OSError as exc:
                QMessageBox.warning(self, "Could not open workflows", str(exc))

        def detect_comfyui(self, quiet: bool = False):
            found = detect_comfyui_root(self.comfy_path.text().strip() or getattr(self.settings, "comfy_path", ""))
            if found:
                self.comfy_path.setText(str(found))
                if not quiet:
                    self.h3_log.append(f"Detected ComfyUI: {found}")
            elif not quiet:
                QMessageBox.information(
                    self,
                    "ComfyUI not detected",
                    "ZeroAI could not find ComfyUI in the common Windows locations. Click Browse and select your ComfyUI folder.",
                )
            self.refresh_h3_status()

        def browse_comfyui(self):
            start = self.comfy_path.text().strip() or str(Path.home())
            path = QFileDialog.getExistingDirectory(self, "Select the ComfyUI folder", start)
            if path:
                normalized = normalize_comfyui_root(path)
                self.comfy_path.setText(str(normalized or Path(path)))
                self.refresh_h3_status()

        def refresh_h3_status(self):
            root = normalize_comfyui_root(self.comfy_path.text().strip())
            if not root or not root.exists():
                self.h3_status.setText("H3: choose or detect your ComfyUI folder to check model files.")
                return
            status = model_status(root)
            ready = [name for name, info in status.items() if info["ready"]]
            missing = [item for item in H3_MODEL_FILES if not status[item.filename]["ready"]]
            if not missing:
                self.h3_status.setText("H3 model files: READY (4/4). Restart ComfyUI if these files were just installed.")
                self.h3_progress.setValue(100)
            else:
                names = ", ".join(item.label for item in missing)
                self.h3_status.setText(f"H3 model files: {len(ready)}/4 installed. Missing: {names}.")

        def install_h3(self):
            root = normalize_comfyui_root(self.comfy_path.text().strip())
            if not root or not (root / "models").exists():
                self.browse_comfyui()
                root = normalize_comfyui_root(self.comfy_path.text().strip())
            if not root or not (root / "models").exists():
                return

            missing = missing_models(root)
            if not missing:
                QMessageBox.information(self, "MiniMax H3", "All required H3 model files are already installed.")
                self.refresh_h3_status()
                return

            answer = QMessageBox.question(
                self,
                "Download MiniMax H3",
                "ZeroAI will download the official MiniMax H3 Ref2VA files into your ComfyUI models folder.\n\n"
                f"Full stack size is about {format_bytes(TOTAL_EXPECTED_BYTES)} and interrupted downloads can resume.\n\n"
                "Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return

            self.settings.comfy_path = str(root)
            self.comfy_path.setText(str(root))
            save_settings(self.settings)
            self.h3_progress.setValue(0)
            self.h3_log.clear()
            self.install_h3_btn.setEnabled(False)
            self.cancel_h3_btn.setEnabled(True)
            self.h3_worker = H3DownloadThread(str(root))
            self.h3_worker.progress_changed.connect(self.on_h3_progress)
            self.h3_worker.log_line.connect(self.h3_log.append)
            self.h3_worker.installed.connect(self.on_h3_installed)
            self.h3_worker.failed.connect(self.on_h3_failed)
            self.h3_worker.start()

        def cancel_h3(self):
            if self.h3_worker:
                self.h3_worker.cancel()
                self.h3_log.append("Cancelling download; partial files will be kept for resume…")

        def on_h3_progress(self, percent: int, text: str):
            self.h3_progress.setValue(percent)
            self.h3_progress_text.setText(text)

        def on_h3_installed(self):
            self.install_h3_btn.setEnabled(True)
            self.cancel_h3_btn.setEnabled(False)
            self.h3_progress.setValue(100)
            self.h3_progress_text.setText("MiniMax H3 installed. Restart ComfyUI, then click Test ComfyUI.")
            self.refresh_h3_status()
            QMessageBox.information(
                self,
                "MiniMax H3 installed",
                "All required model files are installed. Completely restart ComfyUI so it rescans the model folders.",
            )

        def on_h3_failed(self, message: str):
            self.install_h3_btn.setEnabled(True)
            self.cancel_h3_btn.setEnabled(False)
            self.h3_log.append("ERROR: " + message)
            self.refresh_h3_status()
            if "cancelled" not in message.lower():
                QMessageBox.critical(self, "H3 setup failed", message)

        def _download_active(self) -> bool:
            return bool(self.h3_worker and self.h3_worker.isRunning())

        def _warn_download_active(self):
            QMessageBox.information(
                self,
                "H3 download still running",
                "Cancel the active H3 download before closing Settings. Partial files are kept and will resume next time.",
            )

        def accept(self):
            if self._download_active():
                self._warn_download_active()
                return
            super().accept()

        def reject(self):
            if self._download_active():
                self._warn_download_active()
                return
            super().reject()

        def closeEvent(self, event):
            if self._download_active():
                event.ignore()
                self._warn_download_active()
                return
            super().closeEvent(event)

        def apply(self):
            visual_workflow = self.workflow.text().strip()
            super().apply()
            self.settings.comfy_path = self.comfy_path.text().strip()
            self.settings.workflow_path = visual_workflow or BUILTIN_H3_URI
            save_settings(self.settings)

    class EnhancedMainWindow(BaseMainWindow):
        def __init__(self):
            super().__init__()
            if _is_builtin_or_legacy(self.settings.workflow_path):
                self.settings.workflow_path = BUILTIN_H3_URI
                save_settings(self.settings)
            if not getattr(self.settings, "comfy_path", ""):
                found = detect_comfyui_root()
                if found:
                    self.settings.comfy_path = str(found)
                    save_settings(self.settings)
            self.refresh_engine_status()

        def refresh_engine_status(self):
            client = ComfyClient(self.settings.comfy_url)
            if not client.check():
                self.engine_chip.setText("ComfyUI: Offline")
                return
            if self.settings.workflow_path != BUILTIN_H3_URI:
                self.engine_chip.setText("ComfyUI: Online • Custom")
                return
            try:
                ready = client.h3_readiness()
                if ready["ready"]:
                    self.engine_chip.setText("ComfyUI: Online • H3 Ready")
                elif not ready["node_available"]:
                    self.engine_chip.setText("ComfyUI: Online • Update ComfyUI")
                else:
                    self.engine_chip.setText("ComfyUI: Online • H3 Setup")
            except Exception:
                self.engine_chip.setText("ComfyUI: Online • H3 Unchecked")

        def generate_video(self):
            self.sync_project_from_ui()
            if self.settings.workflow_path == BUILTIN_H3_URI:
                if not self.project.references:
                    QMessageBox.warning(self, "Reference needed", "Add at least one AI influencer reference image for MiniMax H3 Ref2VA.")
                    return
                client = ComfyClient(self.settings.comfy_url)
                if not client.check():
                    QMessageBox.warning(self, "ComfyUI offline", "Start ComfyUI first, then try Generate Video again.")
                    return
                try:
                    readiness = client.h3_readiness()
                except Exception:
                    readiness = {"ready": False, "node_available": True, "missing": ["H3 readiness check failed"]}
                if not readiness["ready"]:
                    if not readiness.get("node_available", True):
                        message = (
                            "Your ComfyUI build does not expose the MiniMaxH3ReferenceToVideo node yet. "
                            "Update ComfyUI, restart it, then try again."
                        )
                    else:
                        missing = "\n• ".join(readiness.get("missing", []))
                        message = "MiniMax H3 is not fully installed in ComfyUI. Missing:\n\n• " + missing
                    answer = QMessageBox.question(
                        self,
                        "MiniMax H3 setup required",
                        message + "\n\nOpen ZeroAI Settings to download/repair H3 now?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    if answer == QMessageBox.Yes:
                        self.open_settings()
                    return
            return super().generate_video()

    ui_module.SettingsDialog = EnhancedSettingsDialog
    ui_module.MainWindow = EnhancedMainWindow
