from PySide6.QtWidgets import QStatusBar

import zeroai.ui as ui
from zeroai.h3_integration import install_h3_integration
from zeroai.performance_integration import install_performance_integration

# Keep the v0.1.1 startup guard for packaged builds.
ui.QStatusBar = QStatusBar

# v0.2 adds built-in MiniMax H3 workflows and one-click model setup without
# duplicating the existing main-window implementation.
install_h3_integration(ui)

# v0.3 adds GPU-aware H3 performance controls and real ComfyUI sampler progress.
install_performance_integration(ui)


if __name__ == "__main__":
    raise SystemExit(ui.run_app())
