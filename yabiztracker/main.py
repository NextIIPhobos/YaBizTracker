from __future__ import annotations

import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from .backup_bootstrap import prepare_database
from .crash import CrashHandler
from .ui.main_window import MainWindow


class CrashHandlingApplication(QApplication):
    def notify(self, receiver, event):
        try:
            return super().notify(receiver, event)
        except Exception:
            sys.excepthook(*sys.exc_info())
            return False


def main():
    app = CrashHandlingApplication(sys.argv)
    app.setApplicationName("YaBizTracker")
    app.setStyle("Fusion")
    # Application icon: in a PyInstaller one-file build bundled resources are
    # unpacked under _MEIPASS; in a normal source run icon.png lives beside the
    # project package. Keep a graceful fallback if the icon is missing.
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runtime_dir = getattr(sys, "_MEIPASS", "")
    icon_candidates = []
    if runtime_dir:
        icon_candidates.append(os.path.join(runtime_dir, "icon.png"))
    icon_candidates.append(os.path.join(base_dir, "icon.png"))
    icon_path = next((p for p in icon_candidates if os.path.isfile(p)), None)
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    # In a normal Python run keep data beside the project; in a PyInstaller build
    # keep all user data beside the executable so updates do not hide the database
    # inside a temporary one-file extraction directory.
    context = {"window": None}
    crash_handler = CrashHandler(base_dir, lambda: {
        "version": __import__("yabiztracker").__version__,
        "state": getattr(context.get("window"), "state", None),
        "scan_running": bool(getattr(getattr(context.get("window"), "scan_worker", None), "isRunning", lambda: False)()),
        "recent_operations": list(getattr(getattr(context.get("window"), "logger", None), "recent", []))[-100:],
    })
    crash_handler.install()
    ok, message = prepare_database(base_dir)
    if not ok:
        QMessageBox.critical(None, "База данных", message)
        return 2
    w = MainWindow(base_dir)
    context["window"] = w
    # closeEvent performs the normal shutdown; aboutToQuit is a final idempotent
    # safety net for programmatic QApplication.quit()/exit() paths.
    app.aboutToQuit.connect(w.shutdown)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
