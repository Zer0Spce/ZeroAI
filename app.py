from PySide6.QtWidgets import QStatusBar

import zeroai.ui as ui

# Hotfix guard: ui.py uses QStatusBar during MainWindow construction.
# Keep this alias here so packaged builds launch even if the widget is not
# present in zeroai.ui's explicit QtWidgets import list.
ui.QStatusBar = QStatusBar


if __name__ == "__main__":
    raise SystemExit(ui.run_app())
