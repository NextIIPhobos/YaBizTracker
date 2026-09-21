from __future__ import annotations

import os
import platform
import sys
import threading
import traceback
from datetime import datetime


class CrashHandler:
    def __init__(self, base_dir: str, state_provider=None, logger=None):
        self.base_dir = base_dir
        self.state_provider = state_provider or (lambda: {})
        self.logger = logger
        self._handling = threading.Lock()

    def install(self):
        self._old_excepthook = sys.excepthook
        sys.excepthook = self.excepthook

    def excepthook(self, exc_type, exc_value, exc_tb):
        path = self.write_crash(exc_type, exc_value, exc_tb)
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(None, "Непредвиденная ошибка",
                    "Произошла непредвиденная ошибка.\n\n"
                    "Данные базы не удалены.\n"
                    f"Подробности сохранены в журнал: {path}")
        except Exception:
            pass
        # Do not delegate to the default hook: the user-facing crash report is our source of truth.

    def write_crash(self, exc_type, exc_value, exc_tb) -> str:
        if not self._handling.acquire(blocking=False):
            return "crash handler already running"
        try:
            directory = os.path.join(self.base_dir, "logs", "crash")
            os.makedirs(directory, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            path = os.path.join(directory, f"crash_{stamp}.txt")
            try:
                state = self.state_provider() or {}
            except Exception as exc:
                state = {"state_provider_error": repr(exc)}
            lines = [
                "YaBizTracker crash report",
                f"Timestamp: {datetime.now().isoformat(timespec='seconds')}",
                f"Application version: {state.get('version', 'unknown')}",
                f"Python: {platform.python_version()}",
                f"Platform: {platform.platform()}",
                f"Executable: {sys.executable}",
                f"Thread: {threading.current_thread().name} ({threading.get_ident()})",
                "",
                "Application state:",
            ]
            for key, value in state.items():
                lines.append(f"  {key}: {value}")
            lines.extend(["", "Traceback:", "" ])
            lines.extend(traceback.format_exception(exc_type, exc_value, exc_tb))
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            if self.logger:
                try:self.logger.error("Crash report saved: %s", path)
                except Exception:pass
            return path
        finally:
            self._handling.release()
